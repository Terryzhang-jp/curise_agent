"""
Fulfillment lifecycle tools for AI Chat.

Provides 4 tools:
- get_order_fulfillment: view fulfillment status
- update_order_fulfillment: advance status & update financial info
- record_delivery_receipt: record port delivery acceptance
- attach_order_file: attach uploaded file to order
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from config import settings


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
    "pending": "待处理",
    "inquiry_sent": "已询价",
    "quoted": "已报价",
    "confirmed": "已确认",
    "delivering": "运送中",
    "delivered": "已交货",
    "invoiced": "已开票",
    "paid": "已付款",
}

UPLOAD_DIR = settings.UPLOAD_DIR


def create_fulfillment_tools(registry, ctx):
    """Register fulfillment lifecycle tools into the given registry."""

    @registry.tool(
        description="查看指定订单的履约状态概览（当前状态、交货数据、发票、付款信息）",
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
        },
        group="business",
    )
    def get_order_fulfillment(order_id: int = 0) -> str:
        if not order_id:
            return "Error: 请提供 order_id"
        order_id = int(order_id)

        from models import Order
        order = ctx.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"

        status_label = STATUS_LABELS.get(order.fulfillment_status, order.fulfillment_status)
        lines = [
            f"## 订单 #{order.id} 履约状态",
            f"- 当前状态: {status_label} ({order.fulfillment_status})",
            f"- 文件: {order.filename}",
        ]

        if order.fulfillment_notes:
            lines.append(f"- 备注: {order.fulfillment_notes}")

        # Delivery data
        dd = order.delivery_data
        if dd:
            lines.append("")
            lines.append("## 交货验收")
            lines.append(f"- 交货时间: {dd.get('delivered_at', '-')}")
            lines.append(f"- 收货人: {dd.get('received_by', '-')}")
            lines.append(f"- 接收总量: {dd.get('total_accepted', 0)}")
            lines.append(f"- 拒收总量: {dd.get('total_rejected', 0)}")
            lines.append(f"- 摘要: {dd.get('summary', '-')}")
            items = dd.get("items", [])
            if items:
                lines.append(f"- 明细 ({len(items)} 项):")
                for item in items[:20]:
                    name = item.get("product_name", "?")
                    accepted = item.get("accepted_qty", 0)
                    rejected = item.get("rejected_qty", 0)
                    reason = item.get("rejection_reason", "")
                    line = f"  - {name}: 接收 {accepted}, 拒收 {rejected}"
                    if reason:
                        line += f" ({reason})"
                    lines.append(line)

        # Invoice
        if order.invoice_number:
            lines.append("")
            lines.append("## 发票信息")
            lines.append(f"- 发票号: {order.invoice_number}")
            if order.invoice_amount is not None:
                lines.append(f"- 金额: {order.invoice_amount}")
            if order.invoice_date:
                lines.append(f"- 日期: {order.invoice_date}")

        # Payment
        if order.payment_amount is not None:
            lines.append("")
            lines.append("## 付款信息")
            lines.append(f"- 金额: {order.payment_amount}")
            if order.payment_date:
                lines.append(f"- 日期: {order.payment_date}")
            if order.payment_reference:
                lines.append(f"- 参考号: {order.payment_reference}")

        # Attachments
        attachments = order.attachments or []
        if attachments:
            lines.append("")
            lines.append(f"## 附件 ({len(attachments)} 个)")
            for att in attachments:
                lines.append(f"  - {att.get('original_name', att.get('filename', '?'))}: {att.get('description', '')}")

        return "\n".join(lines)

    @registry.tool(
        description="更新订单履约状态和财务信息。状态必须按顺序推进: pending→inquiry_sent→quoted→confirmed→delivering→delivered→invoiced→paid",
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "fulfillment_status": {
                "type": "STRING",
                "description": "目标状态 (pending/inquiry_sent/quoted/confirmed/delivering/delivered/invoiced/paid)",
                "required": False,
            },
            "invoice_number": {
                "type": "STRING",
                "description": "发票号码",
                "required": False,
            },
            "invoice_amount": {
                "type": "NUMBER",
                "description": "发票金额",
                "required": False,
            },
            "invoice_date": {
                "type": "STRING",
                "description": "发票日期",
                "required": False,
            },
            "payment_amount": {
                "type": "NUMBER",
                "description": "付款金额",
                "required": False,
            },
            "payment_date": {
                "type": "STRING",
                "description": "付款日期",
                "required": False,
            },
            "payment_reference": {
                "type": "STRING",
                "description": "付款参考号",
                "required": False,
            },
            "notes": {
                "type": "STRING",
                "description": "备注",
                "required": False,
            },
        },
        group="business",
    )
    def update_order_fulfillment(
        order_id: int = 0,
        fulfillment_status: str = "",
        invoice_number: str = "",
        invoice_amount: float = 0,
        invoice_date: str = "",
        payment_amount: float = 0,
        payment_date: str = "",
        payment_reference: str = "",
        notes: str = "",
    ) -> str:
        if not order_id:
            return "Error: 请提供 order_id"
        order_id = int(order_id)

        from models import Order
        order = ctx.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"

        changes = []

        # Status transition
        if fulfillment_status and fulfillment_status != order.fulfillment_status:
            current = order.fulfillment_status
            allowed = VALID_TRANSITIONS.get(current, [])
            if fulfillment_status not in allowed:
                current_label = STATUS_LABELS.get(current, current)
                allowed_labels = [f"{STATUS_LABELS.get(s, s)} ({s})" for s in allowed]
                return f"Error: 不能从 {current_label} ({current}) 直接跳到 {fulfillment_status}。允许的下一步: {', '.join(allowed_labels) or '无'}"
            order.fulfillment_status = fulfillment_status
            changes.append(f"状态: {STATUS_LABELS.get(current, current)} → {STATUS_LABELS.get(fulfillment_status, fulfillment_status)}")

        # Financial fields
        if invoice_number:
            order.invoice_number = invoice_number
            changes.append(f"发票号: {invoice_number}")
        if invoice_amount:
            order.invoice_amount = float(invoice_amount)
            changes.append(f"发票金额: {invoice_amount}")
        if invoice_date:
            order.invoice_date = invoice_date
            changes.append(f"发票日期: {invoice_date}")
        if payment_amount:
            order.payment_amount = float(payment_amount)
            changes.append(f"付款金额: {payment_amount}")
        if payment_date:
            order.payment_date = payment_date
            changes.append(f"付款日期: {payment_date}")
        if payment_reference:
            order.payment_reference = payment_reference
            changes.append(f"付款参考号: {payment_reference}")
        if notes:
            order.fulfillment_notes = notes
            changes.append(f"备注: {notes}")

        if not changes:
            return "未提供任何更新字段"

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 保存失败 — {str(e)}"

        return f"订单 #{order_id} 已更新:\n" + "\n".join(f"- {c}" for c in changes)

    @registry.tool(
        description="记录港口交货验收：逐产品记录接收数量、拒收数量和原因。自动将状态设为 delivered。",
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "items_json": {
                "type": "STRING",
                "description": 'JSON 数组字符串，每项: {"product_name":"土豆","product_code":"P001","ordered_qty":1000,"accepted_qty":500,"rejected_qty":500,"rejection_reason":"quality","notes":"发霉变质"}',
            },
            "received_by": {
                "type": "STRING",
                "description": "收货人姓名",
                "required": False,
            },
            "delivered_at": {
                "type": "STRING",
                "description": "交货时间 (ISO 格式，不提供则自动填当前时间)",
                "required": False,
            },
        },
        group="business",
    )
    def record_delivery_receipt(
        order_id: int = 0,
        items_json: str = "",
        received_by: str = "",
        delivered_at: str = "",
    ) -> str:
        if not order_id:
            return "Error: 请提供 order_id"
        order_id = int(order_id)

        from models import Order
        order = ctx.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"

        # Parse items
        if not items_json:
            return "Error: 请提供 items_json（交货明细）"
        try:
            items = json.loads(items_json)
            if not isinstance(items, list):
                return "Error: items_json 必须是 JSON 数组"
        except json.JSONDecodeError as e:
            return f"Error: items_json 解析失败 — {str(e)}"

        # Calculate totals
        total_accepted = sum(item.get("accepted_qty", 0) for item in items)
        total_rejected = sum(item.get("rejected_qty", 0) for item in items)

        rejected_items = [i for i in items if i.get("rejected_qty", 0) > 0]
        if rejected_items:
            summary = f"{len(items)} 个产品中 {len(rejected_items)} 个有拒收，共接收 {total_accepted}，拒收 {total_rejected}"
        else:
            summary = f"{len(items)} 个产品全部接收，共 {total_accepted}"

        delivery_data = {
            "delivered_at": delivered_at or datetime.utcnow().isoformat(),
            "received_by": received_by or "",
            "items": items,
            "total_accepted": total_accepted,
            "total_rejected": total_rejected,
            "summary": summary,
        }

        order.delivery_data = delivery_data

        # Auto-advance status to delivered (allow from delivering or confirmed)
        if order.fulfillment_status in ("delivering", "confirmed"):
            order.fulfillment_status = "delivered"
        elif order.fulfillment_status == "delivered":
            pass  # Already delivered, just update data
        else:
            # Force to delivered for convenience
            order.fulfillment_status = "delivered"

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 保存失败 — {str(e)}"

        return f"订单 #{order_id} 交货验收已记录:\n- {summary}\n- 状态: {STATUS_LABELS.get(order.fulfillment_status, order.fulfillment_status)}"

    @registry.tool(
        description="将当前 chat 会话中上传的图片/文件附加到订单的附件列表",
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "description": {
                "type": "STRING",
                "description": "文件描述（如：港口交货现场照片）",
                "required": False,
            },
        },
        group="business",
    )
    def attach_order_file(order_id: int = 0, description: str = "") -> str:
        if not order_id:
            return "Error: 请提供 order_id"
        order_id = int(order_id)

        from models import Order
        order = ctx.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"

        if not ctx.file_bytes:
            return "Error: 当前会话没有上传文件。请先上传一个文件再调用此工具。"

        # Save file to uploads/
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        ext = ".bin"
        # Try to detect extension from magic bytes
        header = ctx.file_bytes[:8]
        if header[:3] == b"\xff\xd8\xff":
            ext = ".jpg"
        elif header[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        elif header[:4] == b"RIFF" and ctx.file_bytes[8:12] == b"WEBP":
            ext = ".webp"
        elif header[:4] == b"%PDF":
            ext = ".pdf"
        elif header[:2] in (b"PK", b"\x50\x4b"):
            ext = ".xlsx"

        safe_name = f"att_{uuid.uuid4().hex[:8]}{ext}"
        path = os.path.join(UPLOAD_DIR, safe_name)
        with open(path, "wb") as f:
            f.write(ctx.file_bytes)

        attachment = {
            "filename": safe_name,
            "original_name": safe_name,
            "uploaded_at": datetime.utcnow().isoformat(),
            "description": description or "",
        }

        existing = list(order.attachments or [])
        existing.append(attachment)
        order.attachments = existing

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 保存失败 — {str(e)}"

        return f"文件已附加到订单 #{order_id}。当前共 {len(existing)} 个附件。"
