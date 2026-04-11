from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from services.documents.document_order_projection import (
    EDITABLE_DOCUMENT_FIELDS,
    apply_document_field_overrides,
    build_order_payload,
    create_or_update_order_from_document,
    summarize_order_payload,
)
from services.tools.registry_loader import ToolMetaInfo


TOOL_META = {
    "manage_document_order": ToolMetaInfo(
        display_name="文档订单投影",
        group="business",
        description="把文档提取结果投影为订单 payload，或从文档创建订单",
        prompt_description="文档转订单（预览/创建）",
        summary="文档转订单",
    ),
}


def register(registry, ctx=None):
    def _to_float(value) -> float | None:
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

    def _summarize_document_products(document) -> str:
        payload = build_order_payload(document)
        metadata = payload.get("order_metadata") or {}
        products = payload.get("products") or []
        lines = [
            f"## 文档 #{document.id} 产品列表",
            f"- 文档类型: {payload.get('doc_type') or '-'}",
            f"- 产品数: {len(products)}",
            f"- 币种: {metadata.get('currency') or '-'}",
            f"- 元数据总金额: {_format_money(_to_float(metadata.get('total_amount')))}",
            "",
        ]
        if not products:
            lines.append("未识别到任何产品。")
            return "\n".join(lines)

        lines += [
            "| # | 产品 | 数量 | 单价 | 行总价 |",
            "|---|------|------|------|--------|",
        ]
        for idx, product in enumerate(products[:20]):
            name = (
                product.get("product_name")
                or product.get("product_name_en")
                or product.get("description")
                or product.get("product_code")
                or "?"
            )
            qty = product.get("quantity")
            price = _to_float(product.get("unit_price"))
            total = _to_float(product.get("total_price"))
            qty_text = str(qty) if qty not in (None, "") else "-"
            lines.append(
                f"| {idx} | {name[:40]} | {qty_text} | {_format_money(price)} | {_format_money(total)} |"
            )
        if len(products) > 20:
            lines.append(f"\n仅展示前 20 / 共 {len(products)} 行。")
        return "\n".join(lines)

    def _summarize_document_total(document) -> str:
        payload = build_order_payload(document)
        metadata = payload.get("order_metadata") or {}
        products = payload.get("products") or []

        metadata_total = _to_float(metadata.get("total_amount"))
        computed_total = 0.0
        computed_lines = 0
        fallback_lines = 0
        unresolved_lines: list[int] = []

        for idx, product in enumerate(products):
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
                fallback_lines += 1
                continue

            unresolved_lines.append(idx)

        lines = [
            f"## 文档 #{document.id} 总金额计算",
            f"- 文档类型: {payload.get('doc_type') or '-'}",
            f"- 币种: {metadata.get('currency') or '-'}",
            f"- 元数据总金额: {_format_money(metadata_total)}",
            f"- 按产品计算总金额: {_format_money(computed_total if computed_lines else None)}",
            f"- 已参与计算的产品行: {computed_lines}/{len(products)}",
        ]
        if fallback_lines:
            lines.append(f"- 其中 {fallback_lines} 行使用 quantity × unit_price 回推")
        if unresolved_lines:
            preview = ", ".join(str(i) for i in unresolved_lines[:5])
            suffix = " ..." if len(unresolved_lines) > 5 else ""
            lines.append(f"- 无法计算的产品行: {preview}{suffix}")
        if metadata_total is not None and computed_lines:
            diff = round(computed_total - metadata_total, 2)
            lines.append(f"- 与元数据差额: {_format_money(diff)}")
        if not products:
            lines.append("- 阻断原因: 当前没有产品行，无法按产品计算总金额")
        return "\n".join(lines)

    @registry.tool(
        description=(
            "文档转订单工具。通过 action 选择操作:\n"
            "- preview: 预览 document layer 生成的 order payload\n"
            "- create: 从文档创建或更新订单\n"
            "- products: 查看文档级产品列表（尚未建单也可用）\n"
            "- compute_total: 计算文档总金额（优先用 total_price，其次 quantity × unit_price）\n"
            "- update_fields: 更新文档字段修正层（如 currency / destination_port / delivery_date）\n"
            "- clear_fields: 清除文档字段修正层中的指定字段\n\n"
            "示例:\n"
            '  manage_document_order(action="preview", document_id=12)\n'
            '  manage_document_order(action="create", document_id=12)\n'
            '  manage_document_order(action="products", document_id=12)\n'
            '  manage_document_order(action="compute_total", document_id=12)\n'
            '  manage_document_order(action="create", document_id=12, fields=\'{"force": true}\')\n'
            '  manage_document_order(action="update_fields", document_id=12, fields=\'{"currency": "AUD", "destination_port": "Sydney"}\')\n'
            '  manage_document_order(action="clear_fields", document_id=12, fields=\'{"keys": ["currency"]}\')'
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "操作类型: preview | create | products | compute_total | update_fields | clear_fields",
            },
            "document_id": {
                "type": "NUMBER",
                "description": "文档 ID",
            },
            "fields": {
                "type": "STRING",
                "description": "JSON 格式附加参数。create 支持 {\"force\": true}；update_fields 直接传字段键值；clear_fields 传 {\"keys\": [...]}",
                "required": False,
            },
        },
        group="business",
    )
    def manage_document_order(action: str = "", document_id: int = 0, fields: str = "{}") -> str:
        if not action or not document_id:
            return "Error: 需要 action 和 document_id"

        from core.models import Document
        from services.tools._security import scope_to_owner

        # Row-level ownership check (shared helper): employees only see their
        # own documents. Returns "not found" (not "forbidden") to avoid
        # existence leaks.
        query = ctx.db.query(Document).filter(Document.id == int(document_id))
        query = scope_to_owner(query, Document, ctx)
        document = query.first()
        if not document:
            return f"Error: 文档 {document_id} 不存在"

        try:
            parsed_fields = json.loads(fields) if fields and fields != "{}" else {}
        except (json.JSONDecodeError, TypeError):
            parsed_fields = {}

        if action == "preview":
            payload = build_order_payload(document)
            return summarize_order_payload(payload)

        if action == "create":
            from core.models import Order
            force = bool(parsed_fields.get("force", False))
            existing = ctx.db.query(Order).filter(Order.document_id == document.id).first()
            try:
                # "force" from tool user: overwrite existing + allow incomplete.
                # Status is still computed by _resolve_order_status — incomplete
                # documents become "needs_review", never "ready".
                order = create_or_update_order_from_document(
                    document, ctx.db, force=force, allow_incomplete=force,
                )
            except ValueError as exc:
                return f"Error: {exc}"
            ctx.register_order(order.id)
            mode = "复用已有订单" if existing else "新建订单"
            header = (
                f"已复用已有订单 #{order.id}（未重新建单）"
                if existing
                else f"已新建订单 #{order.id}"
            )
            return (
                f"{header}\n"
                f"- 操作: {mode}\n"
                f"- 来源文档: {document.id}\n"
                f"- 状态: {order.status}\n"
                f"- 产品数: {order.product_count}\n"
                f"- 提示: {order.processing_error or '无'}"
            )

        if action == "products":
            return _summarize_document_products(document)

        if action == "compute_total":
            return _summarize_document_total(document)

        if action == "update_fields":
            raw_updates = parsed_fields.get("updates") if isinstance(parsed_fields.get("updates"), dict) else parsed_fields
            editable_updates = {
                key: value for key, value in raw_updates.items()
                if key in EDITABLE_DOCUMENT_FIELDS
            }
            if not editable_updates:
                return (
                    "Error: 没有可更新的字段。支持字段: "
                    + ", ".join(EDITABLE_DOCUMENT_FIELDS)
                )

            apply_document_field_overrides(document, updates=editable_updates)
            document.updated_at = datetime.now(UTC)
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(document, "extracted_data")
            ctx.db.commit()
            ctx.db.refresh(document)

            payload = build_order_payload(document)
            changed = "，".join(f"{k}={v}" for k, v in editable_updates.items())
            return (
                f"已更新文档 #{document.id} 字段: {changed}\n\n"
                + summarize_order_payload(payload)
            )

        if action == "clear_fields":
            keys = parsed_fields.get("keys") or []
            if not isinstance(keys, list):
                return 'Error: clear_fields 需要 fields=\'{"keys": ["currency", ...]}\''
            keys = [str(k) for k in keys if str(k) in EDITABLE_DOCUMENT_FIELDS]
            if not keys:
                return (
                    "Error: 没有可清除的字段。支持字段: "
                    + ", ".join(EDITABLE_DOCUMENT_FIELDS)
                )

            apply_document_field_overrides(document, clear_fields=keys)
            document.updated_at = datetime.now(UTC)
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(document, "extracted_data")
            ctx.db.commit()
            ctx.db.refresh(document)

            payload = build_order_payload(document)
            return (
                f"已清除文档 #{document.id} 的人工修正字段: {', '.join(keys)}\n\n"
                + summarize_order_payload(payload)
            )

        return f"Error: 未知 action '{action}'。支持: preview, create, products, compute_total, update_fields, clear_fields"
