"""
AI Inquiry Bridge — Semantic field mapping + self-review for inquiry generation.

Design principles:
- Exact match first (no AI needed for most cases)
- Single LLM call for semantic mapping (~2s)
- Self-review catches missing/wrong fields, max 2 iterations
- Uncertain fields are skipped (not guessed)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def build_field_mapping(
    order_metadata: dict[str, Any],
    template_field_positions: dict[str, Any],
) -> dict[str, str]:
    """Build template_field → metadata_key mapping.

    Step 1: Exact match — template field key exists directly in metadata
    Step 2: AI semantic match — single LLM call for remaining unmatched fields

    Returns: {"delivery_date": "deliver_on_date", "ship_name": "vessel_name", ...}
    """
    mapping: dict[str, str] = {}
    unmatched_fields: list[str] = []

    meta_keys = set(order_metadata.keys())

    for field_key in template_field_positions:
        if field_key in meta_keys:
            # Exact match — template field key exists in metadata
            mapping[field_key] = field_key
        else:
            unmatched_fields.append(field_key)

    if not unmatched_fields:
        logger.info("Field mapping: all %d fields matched exactly", len(mapping))
        return mapping

    # Step 2: AI semantic mapping for unmatched fields
    logger.info(
        "Field mapping: %d exact, %d need AI mapping",
        len(mapping), len(unmatched_fields),
    )

    ai_mapping = _ai_semantic_mapping(unmatched_fields, order_metadata)
    mapping.update(ai_mapping)

    logger.info(
        "Field mapping complete: %d total (%d exact + %d AI)",
        len(mapping), len(mapping) - len(ai_mapping), len(ai_mapping),
    )
    return mapping


def _ai_semantic_mapping(
    unmatched_fields: list[str],
    order_metadata: dict[str, Any],
) -> dict[str, str]:
    """Single LLM call to semantically map template fields to metadata keys."""
    from services.pdf_analyzer import _get_model

    # Build compact metadata representation (key: value preview)
    metadata_items: dict[str, str] = {}
    for k, v in order_metadata.items():
        if v is not None and str(v).strip():
            val_str = str(v)
            metadata_items[k] = val_str[:100] if len(val_str) > 100 else val_str

    prompt = f"""你是一个询价单字段映射专家。

## 任务
模板需要以下字段，但订单数据的键名可能不同。请建立映射关系。

## 模板需要的字段（未匹配的）:
{json.dumps(unmatched_fields, ensure_ascii=False)}

## 订单数据的所有键值:
{json.dumps(metadata_items, ensure_ascii=False)}

## 规则
- 只映射你确定语义对应的字段（如 delivery_date ↔ deliver_on_date, ship_name ↔ vessel_name）
- 不确定的不要映射
- 键名大小写可能不同，语言可能不同（英文/日文），但语义必须匹配

## 输出
返回纯 JSON 对象（不要 markdown 代码块）。键是模板字段名，值是订单数据中对应的键名。
示例: {{"delivery_date": "deliver_on_date", "ship_name": "vessel_name"}}
没有任何匹配时返回 {{}}"""

    try:
        model = _get_model()
        response = model.generate_content([prompt])
        text = response.text.strip()

        # Handle markdown-wrapped JSON
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)

        result = json.loads(text)
        if not isinstance(result, dict):
            return {}

        # Validate: ensure mapped values actually exist in metadata
        validated: dict[str, str] = {}
        meta_keys = set(order_metadata.keys())
        for template_field, meta_key in result.items():
            if isinstance(meta_key, str) and meta_key in meta_keys:
                validated[template_field] = meta_key

        logger.info("AI mapping: %d/%d fields mapped", len(validated), len(unmatched_fields))
        return validated

    except Exception as e:
        logger.warning("AI semantic mapping failed: %s", e)
        return {}


def review_filled_data(
    filled_cells: dict[str, Any],
    template_field_positions: dict[str, Any],
    order_metadata: dict[str, Any],
) -> list[dict]:
    """AI review of filled inquiry data. Returns list of issues.

    Returns: [{"field": "delivery_date", "cell": "H8", "issue": "...", "suggestion": "..."}]
    """
    from services.pdf_analyzer import _get_model

    # Build filled summary: field → {position, value}
    filled_summary: dict[str, dict] = {}
    for field_key, pos_info in template_field_positions.items():
        position = pos_info if isinstance(pos_info, str) else pos_info.get("position", "")
        if not position:
            continue
        cell_value = filled_cells.get(position, "")
        filled_summary[field_key] = {
            "position": position,
            "value": str(cell_value) if cell_value else "(空)",
        }

    # Build compact metadata for comparison
    metadata_compact: dict[str, str] = {}
    for k, v in order_metadata.items():
        if v is not None and str(v).strip():
            metadata_compact[k] = str(v)[:100]

    prompt = f"""你是一个询价单质检员。请审查以下填充结果：

## 模板字段和填充值:
{json.dumps(filled_summary, ensure_ascii=False)}

## 订单原始数据:
{json.dumps(metadata_compact, ensure_ascii=False)}

## 检查项目:
1. 是否有重要字段遗漏（订单中有数据但模板中对应字段为空）
2. 值是否填错位置（如日期填到了名称字段）
3. 格式是否合理（如日期格式）

## 输出
返回纯 JSON 数组（不要 markdown 代码块）。每个元素:
{{"field": "字段名", "cell": "单元格位置", "issue": "问题描述", "suggestion": "建议的值或修正"}}
没有问题返回空数组 []"""

    try:
        model = _get_model()
        response = model.generate_content([prompt])
        text = response.text.strip()

        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)

        result = json.loads(text)
        if isinstance(result, list):
            logger.info("Review found %d issues", len(result))
            return result
        return []

    except Exception as e:
        logger.warning("AI review failed: %s", e)
        return []


def apply_review_fixes(
    issues: list[dict],
    order_metadata: dict[str, Any],
    field_mapping: dict[str, str],
    template_field_positions: dict[str, Any],
) -> dict[str, str]:
    """Apply review fixes by updating field_mapping based on AI suggestions.

    For each issue where the AI suggests a metadata key that has a value,
    add or update the mapping.

    Returns updated field_mapping.
    """
    meta_keys = set(order_metadata.keys())
    updated = dict(field_mapping)

    for issue in issues:
        field = issue.get("field", "")
        suggestion = issue.get("suggestion", "")

        if not field or not suggestion:
            continue

        # If suggestion looks like a metadata key, add/update mapping
        if suggestion in meta_keys and field in template_field_positions:
            updated[field] = suggestion
            logger.info("Review fix: %s → %s (was: %s)",
                        field, suggestion, field_mapping.get(field, "(unmapped)"))

    return updated
