"""Order overview tool — view order summary info."""

from __future__ import annotations

import json

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "get_order_overview": ToolMetaInfo(
        display_name="订单概览",
        group="business",
        description="查看订单概览（基本信息、匹配统计、询价状态、产品列表前10个）",
        prompt_description="查看订单概览（基本信息、匹配、询价状态）",
        summary="查看订单概览",
    ),
}


def register(registry, ctx=None):
    """Register order overview tool."""

    @registry.tool(
        description="查看指定订单的概览信息（基本信息、匹配统计、询价状态、产品列表前10个）",
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
        },
        group="business",
    )
    def get_order_overview(order_id: int = 0) -> str:
        if not order_id:
            return "Error: 请提供 order_id"
        order_id = int(order_id)

        from models import Order
        order = ctx.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"

        # Track this order for artifact panel
        ctx.register_order(order_id)

        meta = order.order_metadata or {}
        stats = order.match_statistics or {}

        lines = [
            f"## 订单 #{order.id}",
            f"- 文件: {order.filename}",
            f"- 状态: {order.status}",
            f"- PO号: {meta.get('po_number', '-')}",
            f"- 船名: {meta.get('ship_name', '-')}",
            f"- 交货日期: {meta.get('delivery_date') or order.delivery_date or '-'}",
            f"- 币种: {meta.get('currency', '-')}",
            f"- 上传时间: {order.created_at}",
            "",
            f"## 匹配统计",
            f"- 产品总数: {order.product_count}",
            f"- 匹配率: {stats.get('match_rate', '-')}%",
            f"- 已匹配: {stats.get('matched', 0)}",
            f"- 可能匹配: {stats.get('possible', 0)}",
            f"- 未匹配: {stats.get('not_matched', 0)}",
        ]

        # Inquiry status
        if order.inquiry_data:
            files = order.inquiry_data.get("generated_files", [])
            success = [f for f in files if f.get("filename")]
            lines.append("")
            lines.append(f"## 询价单")
            lines.append(f"- 已生成: {len(success)} 份")
            for f in success:
                lines.append(f"  - 供应商 #{f.get('supplier_id')}: {f.get('filename')} ({f.get('product_count', '?')} 产品)")
        else:
            lines.append("")
            lines.append("## 询价单")
            lines.append("- 未生成")

        # Fulfillment status
        lines.append("")
        lines.append(f"## 履约状态")
        lines.append(f"- 当前: {order.fulfillment_status}")
        if order.invoice_number:
            lines.append(f"- 发票号: {order.invoice_number}, 金额: {order.invoice_amount}")
        if order.payment_amount:
            lines.append(f"- 付款: {order.payment_amount} ({order.payment_date})")
        if order.delivery_data:
            dd = order.delivery_data
            lines.append(f"- 交货: {dd.get('summary', '-')}")

        # Product preview (first 10)
        products = order.products or []
        if products:
            lines.append("")
            lines.append(f"## 产品列表（前 {min(10, len(products))} / 共 {len(products)}）")
            for p in products[:10]:
                name = p.get("product_name") or p.get("product_name_en") or p.get("description") or "?"
                qty = p.get("quantity", "?")
                lines.append(f"  - {name} x{qty}")

        # Hint about available deferred tools for common next steps
        lines.append("")
        lines.append("可用操作提示：如需生成询价单，搜索 inquiry 工具；如需管理履约状态，搜索 fulfillment 工具。")

        return "\n".join(lines)
