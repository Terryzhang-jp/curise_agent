"""Template analysis — 3-layer cell classification with Gemini JSON mode.

Every non-empty cell is classified with 3 dimensions:
  1. source_type: order / supplier / company / static / formula / product_header
  2. writable: true (needs filling) / false (keep as-is)
  3. data_from: order_data / supplier_db / company_config / formula / template

Returns cell_map (full classification) + derived field_positions / product_table_config
for backward compatibility.

Falls back to the original single-shot analysis on failure.
"""

from __future__ import annotations

import io
import json
import logging
import time
from typing import Any

from openpyxl import load_workbook
from google import genai
from google.genai import types

from services.agent.config import load_api_key
from services.template_analyzer import _build_cell_text

logger = logging.getLogger(__name__)

_MAX_CELL_TEXT = 15000


# ── Prompt ──────────────────────────────────────────────────────

ANALYSIS_PROMPT = """你是 Excel 询价单/采购单模板结构分析专家。以下是模板的所有非空单元格。

## 模板内容
{cell_text}

## 任务

对**产品表区域之外**的每个非空单元格进行三层分类。
产品表的数据行（行号重复的区域）不要逐行列出，只在 product_table 里定义列映射。

### ① source_type (性质)
- "order" — 订单数据（PO号、日期、船名、航次、交货日期、配送地址等，每次订单不同）
- "supplier" — 供应商信息（供应商名、担当者、TEL、FAX、Email、地址、银行等，每个供应商不同）
- "company" — 本公司/买方信息（公司名、地址、电话等，固定不变）
- "static" — 固定文本（标题、标签文字如"DATE:"、"Invoice:"、装饰、通貨符号等）
- "formula" — Excel 公式（以=开头的值，自动计算）
- "product_header" — 产品表的表头列标题

### ② writable (是否需要填写)
- true — 生成询价单时需要写入新值（order 和 supplier 字段通常为 true）
- false — 保持原样（static、formula、product_header 一定是 false；company 通常 false）

### ③ data_from (数据来源)
- "order_data" — 从订单数据获取
- "supplier_db" — 从供应商数据库获取
- "company_config" — 从公司配置获取
- "formula" — Excel 自动计算
- "template" — 保持模板原值

### ④ field_key (字段标识)
对 writable=true 或 formula 类型，给出语义化英文字段名。
static 和 product_header 的 field_key 为 null。

## 字段名参考

### 订单字段 (order)
po_number, order_date, delivery_date, ship_name, voyage, destination, port_name,
currency, payment_date, payment_method, delivery_address, delivery_contact,
delivery_time_notes, invoice_number

### 供应商字段 (supplier)
supplier_name, supplier_contact, supplier_tel, supplier_fax, supplier_email,
supplier_address, supplier_zip_code, supplier_bank, supplier_account

### 本公司字段 (company)
company_name, company_contact, company_address, company_zip_code,
company_tel, company_fax, company_email

### 公式字段 (formula)
total_amount, sub_total, tax_amount, grand_total, item_amount

## 关键提示
- 标签（如"DATE:"、"Delivery Date:"、"TOTAL:"）是 static，不是 order
- 标签旁边/下方的**值单元格**才是 order/supplier/company
- 判断 company vs supplier：模板中的"发注元"/"买方"/"From"侧 → company；"宛先"/"收件方"/"To"侧 → supplier
- 产品表数据行不要列入 cells，只在 product_table 里定义

## 输出 JSON

{{
  "cell_map": {{
    "A1": {{"source_type": "static", "writable": false, "data_from": "template", "field_key": null, "label": "描述"}},
    "A2": {{"source_type": "order", "writable": true, "data_from": "order_data", "field_key": "ship_name", "label": "船名"}},
    "H16": {{"source_type": "formula", "writable": false, "data_from": "formula", "field_key": "total_amount", "label": "合計", "formula": "=L35"}},
    ...
  }},
  "product_table": {{
    "header_row": 20,
    "start_row": 22,
    "columns": {{"A": "line_number", "B": "po_number", "C": "product_code", ...}},
    "formula_columns": {{"L": "=H*J"}}
  }},
  "notes": "特殊备注"
}}
"""

ORDER_CONTEXT_ADDENDUM = """
## 订单模板提供的字段

重点匹配以下订单模板定义的字段：

### 头部字段
{header_fields_text}

### 产品表列字段
{product_fields_text}

{source_company_text}
"""


# ── Entry point ──────────────────────────────────────────────────

def run_template_analysis_agent(
    file_bytes: bytes,
    order_context: dict | None = None,
) -> dict:
    """Analyze an Excel template using 3-layer cell classification.

    Returns dict with cell_map + derived field_positions/product_table_config
    for backward compatibility.
    """
    start_time = time.time()

    # 1. Parse workbook and build cell text
    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=False)
    except Exception as e:
        logger.error("Failed to load workbook: %s", e)
        return _fallback(file_bytes, order_context, reason=str(e))

    cell_text = _build_cell_text(wb)
    if not cell_text.strip():
        return {
            "cell_map": {},
            "field_positions": {},
            "product_table_config": {},
            "field_mapping_preview": [],
            "notes": "Empty workbook",
        }

    if len(cell_text) > _MAX_CELL_TEXT:
        cell_text = cell_text[:_MAX_CELL_TEXT] + "\n... (内容已截断)"

    # 2. Build prompt
    prompt = ANALYSIS_PROMPT.format(cell_text=cell_text)

    if order_context:
        header_fields = order_context.get("header_fields", [])
        product_fields = order_context.get("product_fields", [])
        source_company = order_context.get("source_company")

        header_text = "\n".join(
            f"- {f['key']}: {f['label']}" for f in header_fields
        ) if header_fields else "(无头部字段)"

        product_text = "\n".join(
            f"- {f['key']}: {f['label']}" for f in product_fields
        ) if product_fields else "(无产品列字段)"

        company_text = f"## 来源公司\n此订单来自: {source_company}" if source_company else ""

        prompt += ORDER_CONTEXT_ADDENDUM.format(
            header_fields_text=header_text,
            product_fields_text=product_text,
            source_company_text=company_text,
        )

    # 3. Single-pass structured extraction
    try:
        api_key = load_api_key("gemini")
        client = genai.Client(api_key=api_key)

        logger.info(
            "Starting 3-layer template analysis (%d chars cell text, order_context=%s)",
            len(cell_text), bool(order_context),
        )

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=15000,
                thinking_config=types.ThinkingConfig(thinking_budget=2048),
            ),
        )

        elapsed = time.time() - start_time
        response_text = response.text.strip()
        logger.info(
            "Template analysis completed in %.1fs (%d chars response)",
            elapsed, len(response_text),
        )

        raw = json.loads(response_text)
        cell_map = raw.get("cell_map", {})
        product_table = raw.get("product_table", {})
        notes = raw.get("notes", "")

        # 4. Derive field_positions from cell_map (backward compat)
        field_positions = _derive_field_positions(cell_map)

        # 5. Normalize product_table_config
        product_table_config = _normalize_product_table(product_table)

        # 6. Build field_mapping_preview from cell_map
        field_mapping_preview = _build_mapping_preview(cell_map)

        logger.info(
            "Analysis result: %d cells in map, %d field_positions, %d product_columns",
            len(cell_map), len(field_positions),
            len(product_table_config.get("columns", {})),
        )

        return {
            "cell_map": cell_map,
            "field_positions": field_positions,
            "product_table_config": product_table_config,
            "field_mapping_preview": field_mapping_preview,
            "notes": notes,
        }

    except Exception as e:
        logger.error("Single-pass analysis failed: %s", e, exc_info=True)
        return _fallback(file_bytes, order_context, reason=str(e))


# ── Derivation helpers ──────────────────────────────────────────


def _derive_field_positions(cell_map: dict) -> dict:
    """Derive field_positions from cell_map: writable cells with field_key."""
    fp = {}
    for pos, info in cell_map.items():
        if info.get("writable") and info.get("field_key"):
            fk = info["field_key"]
            # Avoid duplicates — first occurrence wins
            if fk not in fp:
                fp[fk] = pos
    return fp


def _normalize_product_table(pt: dict) -> dict:
    """Normalize product_table into product_table_config format."""
    if not pt:
        return {}
    config: dict[str, Any] = {}
    if "header_row" in pt:
        config["header_row"] = pt["header_row"]
    if "start_row" in pt:
        config["start_row"] = pt["start_row"]
    # columns: {"A": "line_number", ...}
    cols = pt.get("columns", {})
    config["columns"] = cols
    # formula_columns: could be dict {"L": "=H*J"} or list ["L"]
    fc = pt.get("formula_columns", {})
    if isinstance(fc, dict):
        config["formula_columns"] = list(fc.keys())
        config["formula_column_details"] = fc
    elif isinstance(fc, list):
        config["formula_columns"] = fc
    return config


def _build_mapping_preview(cell_map: dict) -> list:
    """Build field_mapping_preview from cell_map for backward compat."""
    preview = []
    for pos, info in cell_map.items():
        fk = info.get("field_key")
        if not fk:
            continue
        if info.get("source_type") in ("static", "product_header"):
            continue
        preview.append({
            "order_field_key": fk,
            "order_field_label": info.get("label", fk),
            "matched_position": pos,
            "current_cell_value": None,
            "confidence": "high",
            "source": "ai",
        })
    return preview


# ── Fallback ────────────────────────────────────────────────────

def _fallback(
    file_bytes: bytes,
    order_context: dict | None,
    reason: str = "",
) -> dict:
    """Fall back to original single-shot Gemini analysis (without JSON mode)."""
    logger.info("Falling back to legacy analysis (reason: %s)", reason)
    try:
        if order_context:
            from services.template_analyzer import analyze_excel_template_with_order_context
            result = analyze_excel_template_with_order_context(file_bytes, order_context)
        else:
            from services.template_analyzer import analyze_excel_template
            result = analyze_excel_template(file_bytes)
        # Legacy results don't have cell_map
        result.setdefault("cell_map", {})
        return result
    except Exception as e:
        logger.error("Fallback analysis also failed: %s", e)
        return {
            "cell_map": {},
            "field_positions": {},
            "product_table_config": {},
            "field_mapping_preview": [],
            "notes": f"Analysis failed: {e}",
        }
