from __future__ import annotations

import re
from typing import Any

from models import Document, Order
from services.document_order_projection import build_order_payload, get_document_extracted_view


KEY_FIELD_LABELS = {
    "po_number": "PO号",
    "ship_name": "船名",
    "vendor_name": "供应商",
    "delivery_date": "交货日期",
    "order_date": "下单日期",
    "currency": "币种",
    "destination_port": "目的港",
    "total_amount": "总金额",
}
KEY_FIELD_ORDER = tuple(KEY_FIELD_LABELS.keys())
PRODUCT_PREVIEW_LIMIT = 6


def detect_document_id_from_message(user_message: str) -> int | None:
    if not user_message:
        return None

    patterns = [
        r"document_id\s*=\s*(\d+)",
        r"文档\s*ID\s*=\s*(\d+)",
        r"文档\s*#\s*(\d+)",
        r"document\s*#\s*(\d+)",
        r"document\s+(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_message, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def build_document_context_injection(
    db,
    user_message: str,
    scenario: str | None,
    *,
    user_id: int | None = None,
    user_role: str = "employee",
) -> str:
    """Inject document context into the chat prompt.

    Tenant isolation: non-superadmin users can only see documents they own
    (Document.user_id == user_id). Missing ownership → return empty string
    (treat as if the document doesn't exist, to avoid existence leaks).
    """
    if scenario != "document_processing":
        return ""

    document_id = detect_document_id_from_message(user_message)
    if not document_id:
        return ""

    query = db.query(Document).filter(Document.id == document_id)
    if user_role != "superadmin":
        if user_id is None:
            return ""  # no auth context → treat as no access
        query = query.filter(Document.user_id == user_id)
    document = query.first()
    if not document:
        return ""

    # Linked order lookup: scope to same owner for consistency
    order_query = db.query(Order).filter(Order.document_id == document.id)
    if user_role != "superadmin" and user_id is not None:
        order_query = order_query.filter(Order.user_id == user_id)
    linked_order = order_query.first()

    package = build_document_context_package(document, linked_order)
    return render_document_context_package(package)


def build_document_context_package(document: Document, linked_order: Order | None = None) -> dict[str, Any]:
    extracted = get_document_extracted_view(document)
    payload = build_order_payload(document)
    metadata = dict(extracted.get("metadata") or {})
    products = list(payload.get("products") or [])
    field_evidence = dict(payload.get("field_evidence") or {})
    manual_overrides = dict((document.extracted_data or {}).get("manual_overrides") or {})
    confidence = (
        ((document.extracted_data or {}).get("projection") or {})
        .get("purchase_order", {})
        .get("confidence", {})
    )

    totals = _summarize_totals(payload)
    key_fields = []
    for key in KEY_FIELD_ORDER:
        value = payload["order_metadata"].get(key)
        evidence = field_evidence.get(key) or {}
        key_fields.append({
            "key": key,
            "label": KEY_FIELD_LABELS[key],
            "value": value,
            "present": value not in (None, "", []),
            "required": key in ("po_number", "ship_name", "delivery_date"),
            "source": evidence.get("source") or ("user_override" if key in manual_overrides else "metadata"),
        })

    return {
        "document": {
            "id": document.id,
            "filename": document.filename,
            "status": document.status,
            "doc_type": document.doc_type,
            "extraction_method": document.extraction_method,
        },
        "classification": {
            "doc_type": document.doc_type,
            "confidence_verdict": confidence.get("verdict"),
            "confidence_score": confidence.get("score"),
            "confidence_max_score": confidence.get("max_score"),
        },
        "readiness": {
            "ready_for_order_creation": payload.get("ready_for_order_creation", False),
            "missing_fields": list(payload.get("missing_fields") or []),
            "blocking_missing_fields": list(payload.get("blocking_missing_fields") or []),
            "recommended_next_action": _recommended_next_action(payload, linked_order),
        },
        "linked_order": {
            "exists": linked_order is not None,
            "order_id": linked_order.id if linked_order else None,
            "status": linked_order.status if linked_order else None,
        },
        "key_fields": key_fields,
        "product_summary": {
            "product_count": len(products),
            "preview": _product_preview(products),
            **totals,
        },
        "manual_overrides": manual_overrides,
        "metadata": metadata,
    }


def render_document_context_package(package: dict[str, Any]) -> str:
    document = package["document"]
    classification = package["classification"]
    readiness = package["readiness"]
    linked_order = package["linked_order"]
    product_summary = package["product_summary"]
    overrides = package["manual_overrides"]

    lines = [
        "## Document Context Package",
        f"- 文档: #{document['id']} {document['filename']}",
        f"- 状态: {document['status']}",
        f"- 文档类型: {classification.get('doc_type') or '-'}",
    ]
    if classification.get("confidence_verdict"):
        score = classification.get("confidence_score")
        max_score = classification.get("confidence_max_score")
        if score is not None and max_score is not None:
            lines.append(f"- 分类置信度: {classification['confidence_verdict']} ({score}/{max_score})")
        else:
            lines.append(f"- 分类置信度: {classification['confidence_verdict']}")
    if linked_order["exists"]:
        lines.append(f"- 已有关联订单: #{linked_order['order_id']} ({linked_order.get('status') or '-'})")

    lines += [
        "",
        "## 建单判断",
        f"- 可直接建单: {'是' if readiness['ready_for_order_creation'] else '否'}",
        f"- 缺失字段: {_format_list(readiness['blocking_missing_fields'])}",
        f"- 推荐下一步: {readiness['recommended_next_action']}",
        "",
        "## 关键字段",
        "| 字段 | 值 | 状态 | 来源 |",
        "|------|----|------|------|",
    ]
    for field in package["key_fields"]:
        status = "必填" if field["required"] else "可选"
        if not field["present"]:
            status += " / 缺失"
        lines.append(
            f"| {field['label']} | {_format_value(field['value'])} | {status} | {field['source'] or '-'} |"
        )

    lines += [
        "",
        "## 产品摘要",
        f"- 产品数: {product_summary['product_count']}",
        f"- 元数据总金额: {_format_money(product_summary['metadata_total'])}",
        f"- 按产品计算总金额: {_format_money(product_summary['computed_total'])}",
        f"- 已参与计算行数: {product_summary['computed_lines']}/{product_summary['product_count']}",
    ]
    if product_summary["difference"] is not None:
        lines.append(f"- 总金额差额: {_format_money(product_summary['difference'])}")
    if product_summary["unresolved_lines"]:
        lines.append(
            f"- 无法计算的产品行: {', '.join(str(i) for i in product_summary['unresolved_lines'][:5])}"
        )
    if product_summary["preview"]:
        lines.append("- 产品预览:")
        for item in product_summary["preview"]:
            lines.append(
                f"  - #{item['index']} {item['name']} ×{item['quantity']} | 单价 {item['unit_price']} | 行总价 {item['total_price']}"
            )

    if overrides:
        lines += ["", "## 人工修正", f"- 已修正字段: {', '.join(sorted(overrides.keys()))}"]

    lines += [
        "",
        "## Agent 指南",
        "- 先基于这个 context package 决策，不要先重新探索文档。",
        "- 只有在 package 不足以回答、或用户明确要求修改/重算时，才调用工具。",
        "- 如果还没创建订单，不要把 document_id 当成 order_id。",
    ]
    return "\n".join(lines)


def _recommended_next_action(payload: dict[str, Any], linked_order: Order | None) -> str:
    if linked_order is not None:
        return "订单已存在，除非用户要求重建，否则直接进入订单后续处理"
    if payload.get("doc_type") not in (None, "purchase_order"):
        return "暂停，先确认文档类型或让用户手动改成采购订单"
    if not payload.get("products"):
        return "暂停，当前没有识别到产品行"
    blocking = payload.get("blocking_missing_fields") or []
    if blocking:
        return f"暂停，先补齐关键字段: {', '.join(blocking)}"
    return "可以直接创建订单；创建后再进入 process-order"


def _product_preview(products: list[dict[str, Any]]) -> list[dict[str, str]]:
    preview = []
    for idx, product in enumerate(products[:PRODUCT_PREVIEW_LIMIT]):
        preview.append({
            "index": str(idx),
            "name": (
                product.get("product_name")
                or product.get("product_name_en")
                or product.get("description")
                or product.get("product_code")
                or "?"
            ),
            "quantity": _format_value(product.get("quantity")),
            "unit_price": _format_money(_to_float(product.get("unit_price"))),
            "total_price": _format_money(_to_float(product.get("total_price"))),
        })
    return preview


def _summarize_totals(payload: dict[str, Any]) -> dict[str, Any]:
    metadata_total = _to_float((payload.get("order_metadata") or {}).get("total_amount"))
    computed_total = 0.0
    computed_lines = 0
    unresolved_lines: list[int] = []

    for idx, product in enumerate(payload.get("products") or []):
        total_price = _to_float(product.get("total_price"))
        if total_price is not None:
            computed_total += total_price
            computed_lines += 1
            continue

        qty = _to_float(product.get("quantity"))
        unit_price = _to_float(product.get("unit_price"))
        if qty is not None and unit_price is not None:
            computed_total += qty * unit_price
            computed_lines += 1
            continue

        unresolved_lines.append(idx)

    difference = None
    if metadata_total is not None and computed_lines:
        difference = round(computed_total - metadata_total, 2)

    return {
        "metadata_total": metadata_total,
        "computed_total": computed_total if computed_lines else None,
        "computed_lines": computed_lines,
        "difference": difference,
        "unresolved_lines": unresolved_lines,
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}"


def _format_list(values: list[str]) -> str:
    if not values:
        return "无"
    return ", ".join(values)


def _format_value(value: Any) -> str:
    if value in (None, "", []):
        return "-"
    return str(value)
