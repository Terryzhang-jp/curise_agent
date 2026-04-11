"""
Schema-first PDF extraction service.

Phase A: Template Analysis (Settings page) — PDF → batch read → consolidate → Schema
Phase B: Order Extraction (Order upload)   — PDF + Schema → parallel extract → merge → standard format

Designed for large documents (30+ pages) that exceed single-call Vision limits.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────

COMPRESS_THRESHOLD_MB = 15
DEFAULT_BATCH_SIZE = 5
MAX_WORKERS = 4
JPEG_QUALITY = 80
MODEL = "gemini-3-flash-preview"
MAX_RETRIES = 1


# ─── Standard Field Mapping ──────────────────────────────────

_STANDARD_KEY_MAP = {
    "po_number": ["purchase_order_number", "po_no", "order_number", "po_num"],
    "ship_name": ["vessel", "vessel_name"],
    "vendor_name": ["supplier_name", "supplier_address", "supplier"],
    "delivery_date": ["loading_date", "deliver_date", "expected_delivery_date"],
    "order_date": ["date_of_order", "purchase_date", "purchase_order_date"],
    "currency": ["ccy"],
    "destination_port": ["final_destination", "destination", "port_name"],
    "total_amount": ["grand_total", "order_total"],
    "product_code": ["item_number", "item_code", "product_number", "sku"],
    "product_name": ["product_description", "description", "item_description", "item_name"],
    "quantity": ["qty", "order_qty"],
    "unit": ["uom", "unit_of_measure"],
    "unit_price": ["price", "unit_cost"],
    "total_price": ["extended_price", "amount", "line_total"],
    "line_number": ["l_no", "line_no", "seq"],
}


# ─── Gemini Client ────────────────────────────────────────────

def _get_client():
    from google import genai
    from core.config import settings
    return genai.Client(api_key=settings.GOOGLE_API_KEY)


def _image_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def _vision_call(client, images: list[bytes | Image.Image], prompt: str,
                 max_output_tokens: int = 16000) -> dict | list:
    """Gemini Vision: images + prompt -> parsed JSON. Retries once on failure.

    Accepts pre-serialized JPEG bytes (preferred) or PIL Images.
    """
    from google.genai import types

    contents = [types.Part.from_text(text=prompt)]
    for img in images:
        data = img if isinstance(img, bytes) else _image_to_bytes(img)
        contents.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))

    safety = [
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
    ]

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=max_output_tokens,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=1024),
                    safety_settings=safety,
                ),
            )
            text = response.text
            if text is None:
                if attempt < MAX_RETRIES:
                    logger.warning("  Empty response with thinking, retrying without thinking...")
                    time.sleep(1)
                    response = client.models.generate_content(
                        model=MODEL,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            max_output_tokens=max_output_tokens,
                            response_mime_type="application/json",
                            safety_settings=safety,
                        ),
                    )
                    text = response.text
                if text is None:
                    raise ValueError("Gemini returned empty response (possible safety filter)")
            return json.loads(text.strip())
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                logger.warning(f"  Vision call attempt {attempt+1} failed: {e}, retrying...")
                time.sleep(1)
    raise last_err


def _vision_call_no_retry(client, images: list[bytes | Image.Image], prompt: str,
                          max_output_tokens: int = 16000) -> dict | list:
    """Single-attempt Vision call (for best-effort extraction like TextBlocks)."""
    from google.genai import types

    contents = [types.Part.from_text(text=prompt)]
    for img in images:
        data = img if isinstance(img, bytes) else _image_to_bytes(img)
        contents.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
            ],
        ),
    )
    text = response.text
    if text is None:
        raise ValueError("Empty response (safety filter)")
    return json.loads(text.strip())


def _text_call(client, prompt: str, max_output_tokens: int = 16000) -> dict:
    """Gemini text-only call (no images) -> parsed JSON."""
    from google.genai import types

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=2048),
        ),
    )
    text = response.text
    if text is None:
        raise ValueError("Gemini returned empty response")
    return json.loads(text.strip())


# ─── Image Preparation ───────────────────────────────────────

def prepare_images(file_bytes: bytes) -> list[bytes]:
    """PDF -> JPEG bytes list. Converts PIL Images immediately to save memory.

    A 38-page PDF at DPI=150 produces ~228MB of PIL Images but only ~8MB of JPEG bytes.
    By converting eagerly and releasing PIL objects, we reduce peak memory by ~220MB.
    """
    from services.documents.pdf_analyzer import _pdf_bytes_to_images

    size_mb = len(file_bytes) / (1024 * 1024)
    dpi = 150 if size_mb > COMPRESS_THRESHOLD_MB else 200
    logger.info(f"PDF size: {size_mb:.1f}MB -> DPI={dpi}")

    t0 = time.time()
    pil_images = _pdf_bytes_to_images(file_bytes, dpi=dpi)
    n_pages = len(pil_images)

    # Convert to JPEG bytes immediately, then release PIL Images
    jpeg_pages: list[bytes] = []
    for img in pil_images:
        jpeg_pages.append(_image_to_bytes(img))
    del pil_images  # Free ~220MB of PIL Image objects

    logger.info(f"Converted {n_pages} pages in {time.time()-t0:.1f}s "
                f"(JPEG total: {sum(len(b) for b in jpeg_pages) / 1024 / 1024:.1f}MB)")
    return jpeg_pages


# ═══════════════════════════════════════════════════════════════
# Phase A: Template Analysis (Settings page flow)
# ═══════════════════════════════════════════════════════════════

BATCH_READ_PROMPT = """仔细阅读这几页文档，列出你看到的所有信息。

返回 JSON:
{{
  "pages": [
    {{
      "page_number": {page_start},
      "content_type": "cover | metadata | product_data | terms | mixed",
      "observations": [
        {{
          "type": "key_value",
          "key": "字段名（如 PO Number, Vendor Name）",
          "value": "字段值",
          "location": "页面位置描述"
        }},
        {{
          "type": "table_header",
          "columns": ["列名1", "列名2", "..."],
          "location": "页面位置描述"
        }},
        {{
          "type": "table_rows",
          "count": 3,
          "sample": ["第一行简要描述"],
          "location": "页面位置描述"
        }},
        {{
          "type": "text_block",
          "topic": "条款/备注/说明",
          "summary": "简要内容",
          "location": "页面位置描述"
        }}
      ]
    }}
  ]
}}

规则：
- 必须返回 JSON 对象 {{"pages": [...]}}，不要返回 JSON 数组
- 为每一页单独记录，page_number 从 {page_start} 开始递增
- 观察类型: key_value（单个字段）、table_header（表头）、table_rows（数据行）、text_block（文本段落）
- 关键信息不要遗漏：PO号、日期、供应商、收货地址、产品表格列名、条款等
- 产品数据页只需记录行数和前2行样本，不需要逐行提取
- 空白页或无实质内容的页标注 content_type 为 "empty"
"""


def _normalize_batch_read_result(result, page_start: int, batch_size: int) -> list[dict]:
    if isinstance(result, list):
        pages = result
    elif isinstance(result, dict):
        pages = result.get("pages", [result])
    else:
        return []

    for i, page in enumerate(pages):
        if isinstance(page, dict) and "page_number" not in page:
            page["page_number"] = page_start + i

    return pages


def batch_read_pages(client, images: list[bytes]) -> tuple[list[dict], int, int]:
    """Read all pages in batches. Returns (pages, success_count, total_batches)."""
    all_page_results = []

    batches = []
    for i in range(0, len(images), DEFAULT_BATCH_SIZE):
        batch_images = images[i:i + DEFAULT_BATCH_SIZE]
        page_start = i + 1
        batches.append((batch_images, page_start))

    logger.info(f"Template analysis: {len(images)} pages -> {len(batches)} batches")

    total_start = time.time()
    success_count = 0

    with ThreadPoolExecutor(max_workers=min(len(batches), MAX_WORKERS)) as pool:
        futures = {}
        for idx, (batch_images, page_start) in enumerate(batches):
            prompt = BATCH_READ_PROMPT.format(page_start=page_start)
            future = pool.submit(_vision_call, client, batch_images, prompt)
            futures[future] = (idx, page_start, len(batch_images))

        for future in as_completed(futures):
            idx, page_start, n_pages = futures[future]
            try:
                result = future.result()
                pages = _normalize_batch_read_result(result, page_start, n_pages)
                all_page_results.extend(pages)
                success_count += 1
                logger.info(f"  Batch {idx} (pages {page_start}-{page_start+n_pages-1}): "
                            f"{len(pages)} pages read")
            except Exception as e:
                logger.error(f"  Batch {idx} (pages {page_start}-{page_start+n_pages-1}) "
                             f"failed after retries: {e}")

    all_page_results.sort(key=lambda p: p.get("page_number", 0))

    elapsed = time.time() - total_start
    logger.info(f"Batch reading done: {len(all_page_results)} pages in {elapsed:.1f}s "
                f"({success_count}/{len(batches)} batches succeeded)")
    return all_page_results, success_count, len(batches)


CONSOLIDATE_PROMPT = """基于以下逐页观察结果，总结这个文档的完整结构 Schema。

## 逐页观察
{observations_json}

## 要求

返回 JSON:
{{
  "document_type": "文档类型（如 Purchase Order, Invoice, Quotation）",
  "attribute_groups": [
    {{
      "name": "属性组名称（中文）",
      "name_en": "Group Name (English)",
      "type": "single",
      "description": "这个组包含什么信息",
      "attributes": [
        {{
          "key": "snake_case_key",
          "label": "文档中的原始标签",
          "type": "text | date | number | currency",
          "sample_value": "示例值",
          "required": true
        }}
      ]
    }},
    {{
      "name": "产品列表",
      "name_en": "Product List",
      "type": "repeating",
      "description": "产品/行项目表格",
      "columns": [
        {{
          "key": "snake_case_key",
          "label": "文档中的列标题",
          "type": "text | number | currency",
          "sample_value": "示例值"
        }}
      ],
      "estimated_row_count": 100
    }},
    {{
      "name": "条款与条件",
      "name_en": "Terms & Conditions",
      "type": "text_block",
      "description": "法律条款、付款条件等",
      "attributes": [
        {{
          "key": "terms_text",
          "label": "条款内容",
          "type": "text"
        }}
      ]
    }}
  ],
  "page_layout": {{
    "total_pages": 38,
    "cover_pages": [1],
    "metadata_pages": [1, 2],
    "data_pages": [2, 3, 4, 5],
    "terms_pages": [36, 37, 38]
  }},
  "notes": "任何特殊说明"
}}

规则：
- attribute_groups 的 type 只有三种: single（单值字段组）、repeating（重复行/表格）、text_block（大段文本）
- 每个 single 组应该把相关的字段聚合在一起（如"供应商信息"包含公司名、地址、联系人）
- repeating 组用 columns 描述表格列结构
- 重要：如果某一列同时包含产品代码和产品名称（如 "99PRD010588 - APPLE GRANNY SMITH"），请拆成两个列: product_code 和 product_name
- 重要：单位(unit)、数量(quantity)、单价(unit_price) 必须是独立的列。如果某一列同时包含数量和单位（如 "2.2KG"、"15CT"），请拆成 quantity（纯数字）和 unit（纯文本，如 KG、CT、EA）两个列
- 属性的 type: text、date（日期）、number（数字）、currency（金额）
- required 标记该字段是否必须存在
- page_layout.data_pages 必须列出所有包含产品数据的页码（完整列表，不要用省略号）
- 从观察中归纳，不要编造未观察到的内容
"""


def consolidate_schema(client, page_observations: list[dict]) -> dict:
    """Consolidate per-page observations into a document Schema."""
    obs_json = json.dumps(page_observations, ensure_ascii=False, indent=1)

    # Trim if too long: keep first 15 + summary + last 5
    if len(obs_json) > 30000:
        n = len(page_observations)
        keep_head = min(15, n)
        keep_tail = min(5, max(0, n - keep_head))
        middle_count = n - keep_head - keep_tail
        trimmed = page_observations[:keep_head]
        if middle_count > 0:
            trimmed.append({
                "page_number": "...",
                "content_type": "product_data",
                "observations": [{"type": "note",
                                  "value": f"中间 {middle_count} 页为重复产品数据"}]
            })
        trimmed.extend(page_observations[-keep_tail:] if keep_tail > 0 else [])
        obs_json = json.dumps(trimmed, ensure_ascii=False, indent=1)

    prompt = CONSOLIDATE_PROMPT.format(observations_json=obs_json)

    logger.info(f"Consolidating schema from {len(page_observations)} pages "
                f"(prompt: {len(prompt)} chars)")
    t0 = time.time()
    schema = _text_call(client, prompt, max_output_tokens=8000)
    logger.info(f"Schema consolidation done in {time.time()-t0:.1f}s")
    return schema


def analyze_template(file_bytes: bytes) -> dict:
    """Full template analysis pipeline: PDF -> Schema.

    Returns schema dict with attribute_groups, page_layout, _timing.
    """
    total_start = time.time()

    images = prepare_images(file_bytes)
    client = _get_client()

    page_observations, ok_batches, total_batches = batch_read_pages(client, images)

    schema = consolidate_schema(client, page_observations)

    schema["_timing"] = {
        "total": round(time.time() - total_start, 2),
        "pages": len(images),
        "batch_success_rate": f"{ok_batches}/{total_batches}",
        "pages_observed": len(page_observations),
    }

    return schema


# ═══════════════════════════════════════════════════════════════
# Phase B: Order Extraction (Order upload flow)
# ═══════════════════════════════════════════════════════════════

def _build_metadata_prompt(schema: dict) -> str:
    groups = schema.get("attribute_groups", [])

    single_parts = []
    for g in groups:
        if g.get("type") == "single":
            attrs = g.get("attributes", [])
            kv_pairs = ", ".join('"' + a["key"] + '": "值"' for a in attrs)
            single_parts.append(f'    "{g["name"]}": {{{kv_pairs}}}')

    return f"""从这几页中提取元数据（非产品表格数据）。

返回 JSON 对象:
{{
  "single_values": {{
{chr(10).join(single_parts)}
  }}
}}

规则：
- 只提取 single_values（PO号、日期、供应商名等），不提取产品行
- 数字用数值类型，日期保持原始格式
- 找不到的字段用 null
- 必须返回 JSON 对象"""


def _build_products_prompt(schema: dict) -> str:
    groups = schema.get("attribute_groups", [])

    repeating_parts = []
    for g in groups:
        if g.get("type") == "repeating":
            cols = g.get("columns", [])
            col_obj = ", ".join('"' + c["key"] + '": "值"' for c in cols)
            group_key = g.get("name_en", g["name"]).lower().replace(" ", "_")
            repeating_parts.append((group_key, col_obj, g["name"]))

    if not repeating_parts:
        repeating_parts = [("products", '"field": "value"', "产品")]

    products_json = ""
    for key, col_obj, name in repeating_parts:
        products_json += f'  "{key}": [\n    {{{col_obj}}}\n  ],\n'

    return f"""从这几页中提取所有产品/行项目数据。

返回 JSON 对象:
{{
{products_json.rstrip().rstrip(",")}
}}

规则：
- 提取所有产品行，跳过空行、页眉页脚
- 数字用数值类型（不要字符串），文本用字符串
- 看不到的字段用 null
- 只提取产品表格数据，不要提取页眉的元信息
- 必须返回 JSON 对象 {{...}}，不要返回数组 [...]"""


def _build_textblocks_prompt(schema: dict) -> str:
    groups = schema.get("attribute_groups", [])

    text_parts = []
    for g in groups:
        if g.get("type") == "text_block":
            for attr in g.get("attributes", []):
                text_parts.append(f'  "{attr["key"]}": "完整文本内容"')

    if not text_parts:
        text_parts = ['"terms": "内容"']

    return f"""从这几页中提取条款、条件、说明等文本内容。

返回 JSON 对象:
{{
{chr(10).join(text_parts)}
}}

规则：
- 提取完整的文本内容，不要截断
- 必须返回 JSON 对象"""


def _compute_batch_size(schema: dict, n_data_pages: int) -> int:
    groups = schema.get("attribute_groups", [])
    estimated_rows = 0
    for g in groups:
        if g.get("type") == "repeating":
            estimated_rows = max(estimated_rows, g.get("estimated_row_count", 0))

    if estimated_rows == 0 or n_data_pages == 0:
        return DEFAULT_BATCH_SIZE

    products_per_page = estimated_rows / n_data_pages
    if products_per_page <= 0:
        return DEFAULT_BATCH_SIZE

    batch_size = max(2, min(15, int(40 / products_per_page)))
    logger.info(f"Adaptive batch_size={batch_size} "
                f"(~{products_per_page:.1f} products/page, ~{batch_size * products_per_page:.0f}/batch)")
    return batch_size


def _get_page_ranges(schema: dict, total_pages: int) -> tuple[list[int], list[int], list[int]]:
    layout = schema.get("page_layout", {})
    metadata_pages = layout.get("metadata_pages", [1])
    data_pages = layout.get("data_pages", list(range(1, total_pages + 1)))
    terms_pages = layout.get("terms_pages", [])
    schema_total = layout.get("total_pages", total_pages)

    def _clean(pages):
        return sorted(set(int(p) for p in pages if isinstance(p, (int, float)) and 1 <= p <= total_pages))

    clean_terms = _clean(terms_pages)
    clean_meta = _clean(metadata_pages)
    clean_data = _clean(data_pages)

    # When document is shorter than the schema's reference PDF,
    # terms pages (usually at the end) get clipped out entirely.
    # Re-map them proportionally: if schema had terms on last N pages,
    # use the last N pages of the actual document instead.
    if terms_pages and not clean_terms and total_pages < schema_total:
        n_terms = len(terms_pages)
        remapped = list(range(max(1, total_pages - n_terms + 1), total_pages + 1))
        clean_terms = remapped
        # Also add last page to metadata (terms often contain destination info)
        for p in remapped:
            if p not in clean_meta:
                clean_meta.append(p)
        clean_meta.sort()
        logger.info(f"Page layout adjusted: terms_pages remapped to {remapped} "
                    f"(doc has {total_pages} pages, schema expects {schema_total})")

    return clean_meta, clean_data, clean_terms


def _parallel_extract(client, images: list[bytes], page_indices: list[int],
                      prompt: str, batch_size: int, label: str,
                      max_output_tokens: int = 16000) -> list[dict]:
    if not page_indices:
        return []

    batches = []
    for i in range(0, len(page_indices), batch_size):
        chunk_indices = page_indices[i:i + batch_size]
        chunk_images = [images[idx] for idx in chunk_indices]
        batches.append((chunk_images, chunk_indices))

    logger.info(f"{label}: {len(page_indices)} pages -> {len(batches)} batches (size={batch_size})")

    results = []
    t0 = time.time()
    ok_count = 0

    with ThreadPoolExecutor(max_workers=min(len(batches), MAX_WORKERS)) as pool:
        futures = {}
        for idx, (chunk_images, chunk_indices) in enumerate(batches):
            future = pool.submit(_vision_call, client, chunk_images, prompt, max_output_tokens)
            futures[future] = (idx, chunk_indices)

        for future in as_completed(futures):
            idx, chunk_indices = futures[future]
            try:
                raw = future.result()
                if isinstance(raw, list):
                    result = {"_items": raw}
                elif isinstance(raw, dict):
                    result = raw
                else:
                    result = {}
                result["_batch_idx"] = idx
                results.append(result)
                ok_count += 1
            except Exception as e:
                page_range = f"{chunk_indices[0]+1}-{chunk_indices[-1]+1}"
                logger.error(f"  {label} batch {idx} (pages {page_range}) failed: {e}")

    results.sort(key=lambda r: r.get("_batch_idx", 0))
    logger.info(f"{label} done in {time.time()-t0:.1f}s ({ok_count}/{len(batches)} batches)")
    return results


def extract_with_schema(client, images: list[bytes], schema: dict) -> dict:
    """Extract order data using pre-defined Schema, with page-type routing."""
    total_pages = len(images)
    metadata_pages, data_pages, terms_pages = _get_page_ranges(schema, total_pages)

    meta_indices = [p - 1 for p in metadata_pages]
    data_indices = [p - 1 for p in data_pages]
    terms_indices = [p - 1 for p in terms_pages]

    batch_size = _compute_batch_size(schema, len(data_pages))

    meta_prompt = _build_metadata_prompt(schema)
    meta_results = _parallel_extract(
        client, images, meta_indices, meta_prompt,
        batch_size=max(len(meta_indices), 1), label="Metadata",
        max_output_tokens=4000)

    product_prompt = _build_products_prompt(schema)
    product_results = _parallel_extract(
        client, images, data_indices, product_prompt,
        batch_size=batch_size, label="Products",
        max_output_tokens=16000)

    text_results = []
    if terms_indices:
        text_prompt = _build_textblocks_prompt(schema)
        try:
            raw = _vision_call_no_retry(
                client, [images[i] for i in terms_indices], text_prompt,
                max_output_tokens=8000)
            if isinstance(raw, dict):
                text_results = [raw]
            logger.info(f"TextBlocks: extracted from {len(terms_indices)} pages")
        except Exception as e:
            logger.warning(f"TextBlocks: skipped ({e}). Legal terms can be viewed in the PDF directly.")

    return merge_extraction_results(meta_results, product_results, text_results, schema)


def merge_extraction_results(meta_results: list[dict], product_results: list[dict],
                             text_results: list[dict], schema: dict) -> dict:
    merged = {
        "single_values": {},
        "products": [],
        "text_blocks": {},
    }

    for result in meta_results:
        for group_name, values in result.get("single_values", {}).items():
            if not isinstance(values, dict):
                continue
            if group_name not in merged["single_values"]:
                merged["single_values"][group_name] = {}
            for key, val in values.items():
                if val is not None and key not in merged["single_values"][group_name]:
                    merged["single_values"][group_name][key] = val

    repeating_keys = set()
    for g in schema.get("attribute_groups", []):
        if g.get("type") == "repeating":
            repeating_keys.add(g.get("name_en", g["name"]).lower().replace(" ", "_"))

    for result in product_results:
        found_any = False
        for key in repeating_keys:
            items = result.get(key, [])
            if isinstance(items, list):
                merged["products"].extend(items)
                found_any = True

        if not found_any:
            for fallback_key in ["products", "product_list", "_items"]:
                items = result.get(fallback_key, [])
                if isinstance(items, list) and items:
                    merged["products"].extend(items)
                    found_any = True
                    break

            if not found_any:
                for k, v in result.items():
                    if k.startswith("_"):
                        continue
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        merged["products"].extend(v)
                        break

    for result in text_results:
        for key, val in result.items():
            if key.startswith("_") or not isinstance(val, str):
                continue
            existing = merged["text_blocks"].get(key, "")
            if len(val) > len(existing):
                merged["text_blocks"][key] = val

    merged["products"] = _dedup_products(merged["products"])
    merged["products"] = _split_code_name(merged["products"])

    return merged


def _dedup_products(products: list[dict]) -> list[dict]:
    if not products:
        return []

    for p in products:
        ln = p.get("line_number")
        if ln is not None:
            try:
                p["line_number"] = int(ln)
            except (ValueError, TypeError):
                pass

    has_ln = sum(1 for p in products if isinstance(p.get("line_number"), int)) > len(products) * 0.5

    if has_ln:
        seen = {}
        no_ln = []
        for p in products:
            ln = p.get("line_number")
            if not isinstance(ln, int):
                no_ln.append(p)
                continue
            if ln not in seen:
                seen[ln] = p
            else:
                old_count = sum(1 for v in seen[ln].values() if v is not None)
                new_count = sum(1 for v in p.values() if v is not None)
                if new_count > old_count:
                    seen[ln] = p
        result = sorted(seen.values(), key=lambda p: p.get("line_number", 0))
        result.extend(no_ln)
    else:
        seen = {}
        for p in products:
            key = (str(p.get("product_code", "")), str(p.get("product_name", "")))
            if key == ("", ""):
                key = (str(p.get("item_number_description", "")),)
            if key not in seen:
                seen[key] = p
        result = list(seen.values())

    logger.info(f"Dedup: {len(products)} raw -> {len(result)} unique")
    return result


_CODE_NAME_PATTERN = re.compile(
    r'^(\d{2}[A-Z]{3}\d{4,})\s*[-\u2013\u2014]+\s*(.+)$'
)
_CODE_NAME_PATTERN2 = re.compile(
    r'^(\d{2}[A-Z]{3}\d{4,})\s{2,}(.{3,})$'
)

_CODE_ALIASES = {"item_number", "item_code", "product_code", "code", "sku"}
_NAME_ALIASES = {"product_description", "description", "product_name", "item_name", "name"}


def _split_code_name(products: list[dict]) -> list[dict]:
    for p in products:
        if not p.get("product_code"):
            for alias in _CODE_ALIASES:
                if alias in p and p[alias]:
                    p["product_code"] = p[alias]
                    break

        if not p.get("product_name"):
            for alias in _NAME_ALIASES:
                if alias in p and p[alias]:
                    p["product_name"] = p[alias]
                    break

        if p.get("product_code") and p.get("product_name"):
            continue

        combined = None
        for candidate in ["item_number_description", "item_number", "description"]:
            val = p.get(candidate)
            if isinstance(val, str) and len(val) > 10:
                combined = val
                break

        if not combined:
            continue

        m = _CODE_NAME_PATTERN.match(combined.strip())
        if not m:
            m = _CODE_NAME_PATTERN2.match(combined.strip())

        if m:
            p["product_code"] = m.group(1)
            p["product_name"] = m.group(2).strip()
        else:
            if not p.get("product_name"):
                p["product_name"] = combined

    return products


# ═══════════════════════════════════════════════════════════════
# Field Mapping (Schema keys → standard order_metadata keys)
# ═══════════════════════════════════════════════════════════════

def _infer_field_mapping(schema: dict) -> dict:
    """Auto-map schema attribute/column keys to standard keys.

    Returns {schema_key: standard_key} for all matched keys.
    """
    # Build reverse lookup: alias -> standard_key
    reverse = {}
    for std_key, aliases in _STANDARD_KEY_MAP.items():
        reverse[std_key] = std_key
        for alias in aliases:
            reverse[alias] = std_key

    mapping = {}

    for group in schema.get("attribute_groups", []):
        items = group.get("attributes", []) + group.get("columns", [])
        for item in items:
            key = item.get("key", "")
            if not key:
                continue
            normalized = key.lower().strip()
            if normalized in reverse:
                mapping[key] = reverse[normalized]

    return mapping


def _apply_field_mapping(raw_data: dict, schema: dict) -> dict:
    """Convert extract_with_schema output to standard order format.

    Input:  {single_values: {group: {key: val}}, products: [...], text_blocks: {...}}
    Output: {order_metadata: {...}, products: [...], extraction_method, ...}
    """
    from services.orders.order_processor import normalize_metadata

    field_mapping = schema.get("field_mapping", {})

    # Build reverse: schema_key -> standard_key
    reverse = {}
    for sk, std in field_mapping.items():
        reverse[sk.lower()] = std

    # 1. Flatten single_values -> raw metadata dict
    raw_meta = {}
    for group_name, values in raw_data.get("single_values", {}).items():
        if not isinstance(values, dict):
            continue
        for key, val in values.items():
            if val is None:
                continue
            std_key = reverse.get(key.lower(), key)
            if std_key not in raw_meta or raw_meta[std_key] is None:
                raw_meta[std_key] = val

    # 2. Normalize to standard 8 keys
    order_metadata = normalize_metadata(raw_meta)

    # 3. Map product column names
    products = []
    for p in raw_data.get("products", []):
        mapped = {}
        for key, val in p.items():
            std_key = reverse.get(key.lower(), key)
            mapped[std_key] = val
        products.append(mapped)

    return {
        "order_metadata": order_metadata,
        "products": products,
    }


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def extract_order_with_schema(file_bytes: bytes, schema: dict) -> dict:
    """Full order extraction: PDF + Schema -> standard format.

    Output format matches vision_extract():
    {order_metadata, products, extraction_method, page_count, processing_time}
    """
    total_start = time.time()

    images = prepare_images(file_bytes)
    client = _get_client()

    raw_result = extract_with_schema(client, images, schema)

    # Apply field mapping to convert to standard format
    result = _apply_field_mapping(raw_result, schema)

    result["extraction_method"] = "schema_guided"
    result["page_count"] = len(images)
    result["processing_time"] = round(time.time() - total_start, 2)

    logger.info(
        "Schema-guided extraction complete: %d products, %d pages, %.1fs",
        len(result.get("products", [])),
        len(images),
        result["processing_time"],
    )

    return result
