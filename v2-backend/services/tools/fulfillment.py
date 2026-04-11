"""
Fulfillment lifecycle — consolidated per-resource tool.

Replaces 4 per-operation tools with 1 per-resource tool:
  manage_fulfillment(action=get|update|record_delivery|attach_file)
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from config import settings
from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "manage_fulfillment": ToolMetaInfo(
        display_name="履约管理",
        group="business",
        description="订单履约全生命周期: 查看状态、推进状态、记录交货、附加文件",
        prompt_description="订单履约管理（查看/更新状态/交货验收/附件）",
        summary="管理履约",
    ),
}


def register(registry, ctx=None):
    """Auto-discovery compatible alias."""
    create_fulfillment_tools(registry, ctx)


VALID_TRANSITIONS = {
    "pending": ["inquiry_sent"],
    "inquiry_sent": ["quoted"],
    "quoted": ["confirmed"],
    "confirmed": ["delivering"],
    "delivering": ["delivered"],
    "delivered": ["invoiced"],
    "invoiced": ["paid"],
}

STATUS_LABELS = {
    "pending": "待处理", "inquiry_sent": "已询价", "quoted": "已报价",
    "confirmed": "已确认", "delivering": "运送中", "delivered": "已交货",
    "invoiced": "已开票", "paid": "已付款",
}

UPLOAD_DIR = settings.UPLOAD_DIR


def create_fulfillment_tools(registry, ctx):
    """Register consolidated manage_fulfillment tool."""

    # ── Internal helpers ──

    def _get(order) -> str:
        status_label = STATUS_LABELS.get(order.fulfillment_status, order.fulfillment_status)
        lines = [
            f"## 订单 #{order.id} 履约状态",
            f"- 当前状态: {status_label} ({order.fulfillment_status})",
            f"- 文件: {order.filename}",
        ]
        if order.fulfillment_notes:
            lines.append(f"- 备注: {order.fulfillment_notes}")
        dd = order.delivery_data
        if dd:
            lines += ["", "## 交货验收", f"- 交货时间: {dd.get('delivered_at', '-')}",
                       f"- 收货人: {dd.get('received_by', '-')}",
                       f"- 接收: {dd.get('total_accepted', 0)}, 拒收: {dd.get('total_rejected', 0)}",
                       f"- 摘要: {dd.get('summary', '-')}"]
            for item in (dd.get("items") or [])[:20]:
                line = f"  - {item.get('product_name', '?')}: 接收 {item.get('accepted_qty', 0)}, 拒收 {item.get('rejected_qty', 0)}"
                if item.get("rejection_reason"):
                    line += f" ({item['rejection_reason']})"
                lines.append(line)
        if order.invoice_number:
            lines += ["", "## 发票", f"- 发票号: {order.invoice_number}"]
            if order.invoice_amount is not None:
                lines.append(f"- 金额: {order.invoice_amount}")
            if order.invoice_date:
                lines.append(f"- 日期: {order.invoice_date}")
        if order.payment_amount is not None:
            lines += ["", "## 付款", f"- 金额: {order.payment_amount}"]
            if order.payment_date:
                lines.append(f"- 日期: {order.payment_date}")
            if order.payment_reference:
                lines.append(f"- 参考号: {order.payment_reference}")
        attachments = order.attachments or []
        if attachments:
            lines += ["", f"## 附件 ({len(attachments)} 个)"]
            for att in attachments:
                lines.append(f"  - {att.get('original_name', '?')}: {att.get('description', '')}")
        return "\n".join(lines)

    def _update(order, fields: dict) -> str:
        changes = []
        new_status = fields.get("fulfillment_status", "")
        if new_status and new_status != order.fulfillment_status:
            allowed = VALID_TRANSITIONS.get(order.fulfillment_status, [])
            if new_status not in allowed:
                return f"Error: 不能从 {order.fulfillment_status} 跳到 {new_status}。允许: {', '.join(allowed) or '无'}"
            order.fulfillment_status = new_status
            changes.append(f"状态 → {STATUS_LABELS.get(new_status, new_status)}")
        for key, attr in [("invoice_number", "invoice_number"), ("invoice_date", "invoice_date"),
                          ("payment_date", "payment_date"), ("payment_reference", "payment_reference"),
                          ("notes", "fulfillment_notes")]:
            val = fields.get(key, "")
            if val:
                setattr(order, attr, val)
                changes.append(f"{key}: {val}")
        for key, attr in [("invoice_amount", "invoice_amount"), ("payment_amount", "payment_amount")]:
            val = fields.get(key)
            if val is not None and val != 0:
                setattr(order, attr, float(val))
                changes.append(f"{key}: {val}")
        if not changes:
            return "未提供任何更新字段"
        try:
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 保存失败 — {e}"
        return f"订单 #{order.id} 已更新:\n" + "\n".join(f"- {c}" for c in changes)

    def _record_delivery(order, fields: dict) -> str:
        items_json = fields.get("items", "")
        if isinstance(items_json, str):
            try:
                items = json.loads(items_json)
            except json.JSONDecodeError as e:
                return f"Error: items 解析失败 — {e}"
        elif isinstance(items_json, list):
            items = items_json
        else:
            return "Error: items 必须是 JSON 数组"
        if not items:
            return "Error: 请提供 items（交货明细）"
        total_accepted = sum(i.get("accepted_qty", 0) for i in items)
        total_rejected = sum(i.get("rejected_qty", 0) for i in items)
        rejected = [i for i in items if i.get("rejected_qty", 0) > 0]
        summary = f"{len(items)} 个产品中 {len(rejected)} 个有拒收，共接收 {total_accepted}，拒收 {total_rejected}" if rejected else f"{len(items)} 个产品全部接收，共 {total_accepted}"
        order.delivery_data = {
            "delivered_at": fields.get("delivered_at", "") or datetime.utcnow().isoformat(),
            "received_by": fields.get("received_by", ""),
            "items": items, "total_accepted": total_accepted,
            "total_rejected": total_rejected, "summary": summary,
        }
        if order.fulfillment_status in ("delivering", "confirmed", "delivered"):
            order.fulfillment_status = "delivered"
        try:
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 保存失败 — {e}"
        return f"订单 #{order.id} 交货验收已记录:\n- {summary}\n- 状态: {STATUS_LABELS.get(order.fulfillment_status, order.fulfillment_status)}"

    def _attach_file(order, fields: dict) -> str:
        if not ctx.file_bytes:
            return "Error: 当前会话没有上传文件。请先上传文件。"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        header = ctx.file_bytes[:8]
        ext = ".bin"
        if header[:3] == b"\xff\xd8\xff": ext = ".jpg"
        elif header[:8] == b"\x89PNG\r\n\x1a\n": ext = ".png"
        elif header[:4] == b"%PDF": ext = ".pdf"
        elif header[:2] in (b"PK", b"\x50\x4b"): ext = ".xlsx"
        from services.common.file_storage import storage
        safe_name = f"att_{uuid.uuid4().hex[:8]}{ext}"
        storage.upload("attachments", safe_name, ctx.file_bytes)
        attachment = {"filename": safe_name, "original_name": safe_name,
                      "uploaded_at": datetime.utcnow().isoformat(),
                      "description": fields.get("description", "")}
        existing = list(order.attachments or [])
        existing.append(attachment)
        order.attachments = existing
        try:
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 保存失败 — {e}"
        return f"文件已附加到订单 #{order.id}。共 {len(existing)} 个附件。"

    # ── Consolidated tool ──

    @registry.tool(
        description=(
            "订单履约管理。通过 action 参数选择操作:\n"
            "- get: 查看履约状态（交货、发票、付款）\n"
            "- update: 更新状态/财务信息 (fields: fulfillment_status, invoice_number, invoice_amount, payment_amount 等)\n"
            "- record_delivery: 记录交货验收 (fields: items=[{product_name, accepted_qty, rejected_qty}], received_by)\n"
            "- attach_file: 将上传文件附加到订单 (fields: description)\n\n"
            "状态流: pending→inquiry_sent→quoted→confirmed→delivering→delivered→invoiced→paid\n\n"
            "示例:\n"
            '  manage_fulfillment(action="get", order_id=123)\n'
            '  manage_fulfillment(action="update", order_id=123, fields=\'{"fulfillment_status": "delivered"}\')\n'
            '  manage_fulfillment(action="record_delivery", order_id=123, fields=\'{"items": [{"product_name": "土豆", "accepted_qty": 500}]}\')'
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "操作类型: get | update | record_delivery | attach_file",
            },
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "fields": {
                "type": "STRING",
                "description": "JSON 格式的额外参数 (按 action 不同)",
                "required": False,
            },
        },
        group="business",
    )
    def manage_fulfillment(action: str = "", order_id: int = 0, fields: str = "{}") -> str:
        if not action or not order_id:
            return "Error: 需要 action 和 order_id"
        order_id = int(order_id)
        from models import Order
        from services.tools._security import scope_to_owner
        query = ctx.db.query(Order).filter(Order.id == order_id)
        query = scope_to_owner(query, Order, ctx)
        order = query.first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"
        try:
            parsed = json.loads(fields) if fields and fields != "{}" else {}
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        if action == "get":
            return _get(order)
        elif action == "update":
            return _update(order, parsed)
        elif action == "record_delivery":
            return _record_delivery(order, parsed)
        elif action == "attach_file":
            return _attach_file(order, parsed)
        else:
            return f"Error: 未知 action '{action}'。支持: get, update, record_delivery, attach_file"
