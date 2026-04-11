"""Order management tool — consolidated per-resource tool.

Replaces 3 per-operation tools (get_order_overview, get_order_products, update_match_result)
with 1 per-resource tool: manage_order(action=overview|products|update_match).

Design follows Anthropic's "Writing Tools for Agents" guide:
  "Instead of get_customer_by_id + list_transactions, implement get_customer_context"
"""

from __future__ import annotations

import json
import logging

from services.tools.registry_loader import ToolMetaInfo

logger = logging.getLogger(__name__)

TOOL_META = {
    "manage_order": ToolMetaInfo(
        display_name="订单管理",
        group="business",
        description="订单查看与编辑: 概览、产品列表、匹配修改",
        prompt_description="订单管理（概览/产品列表/匹配修改）",
        summary="管理订单",
    ),
}


def register(registry, ctx=None):
    """Register consolidated manage_order tool."""

    # ── Internal helpers (not registered as separate tools) ──

    def _overview(order) -> str:
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
        if order.inquiry_data:
            files = order.inquiry_data.get("generated_files", [])
            success = [f for f in files if f.get("filename")]
            lines += ["", f"## 询价单", f"- 已生成: {len(success)} 份"]
            for f in success:
                lines.append(f"  - 供应商 #{f.get('supplier_id')}: {f.get('filename')} ({f.get('product_count', '?')} 产品)")
        else:
            lines += ["", "## 询价单", "- 未生成"]
        lines += ["", f"## 履约状态", f"- 当前: {order.fulfillment_status}"]
        if order.invoice_number:
            lines.append(f"- 发票号: {order.invoice_number}, 金额: {order.invoice_amount}")
        if order.payment_amount:
            lines.append(f"- 付款: {order.payment_amount} ({order.payment_date})")
        if order.delivery_data:
            lines.append(f"- 交货: {order.delivery_data.get('summary', '-')}")
        products = order.products or []
        if products:
            lines += ["", f"## 产品列表（前 {min(10, len(products))} / 共 {len(products)}）"]
            for p in products[:10]:
                name = p.get("product_name") or p.get("product_name_en") or p.get("description") or "?"
                lines.append(f"  - {name} x{p.get('quantity', '?')}")
        return "\n".join(lines)

    def _products(order, status_filter: str = "") -> str:
        products = order.products or []
        match_results = order.match_results or []
        match_map = {}
        for mr in match_results:
            idx = mr.get("index", mr.get("product_index"))
            if idx is not None:
                match_map[idx] = mr
        lines = [f"## 订单 #{order.id} 产品列表 (共 {len(products)} 个)"]
        if status_filter:
            lines[0] += f" — 过滤: {status_filter}"
        lines += ["", "| # | 产品名 | 数量 | 匹配状态 | 匹配产品 Code | 供应商 |",
                   "|---|--------|------|---------|-------------|--------|"]
        shown = 0
        for i, p in enumerate(products):
            mr = match_map.get(i, {})
            status = mr.get("match_status", mr.get("status", "not_matched"))
            matched_prod = mr.get("matched_product") or {}
            if status_filter and status != status_filter:
                continue
            name = p.get("product_name") or p.get("product_name_en") or p.get("description") or "?"
            code = matched_prod.get("code", "-")
            supplier = matched_prod.get("supplier_name", mr.get("supplier_name", "-"))
            lines.append(f"| {i} | {name[:40]} | {p.get('quantity', '?')} | {status} | {code} | {supplier} |")
            shown += 1
        if shown == 0 and status_filter:
            lines.append(f"| - | 无匹配 '{status_filter}' 状态的产品 | - | - | - | - |")
        lines.append(f"\n共显示 {shown}/{len(products)} 个产品。")
        status_counts: dict[str, int] = {}
        for mr in match_results:
            s = mr.get("match_status", mr.get("status", "not_matched"))
            status_counts[s] = status_counts.get(s, 0) + 1
        if status_counts:
            lines.append(f"匹配统计: {', '.join(f'{k}={v}' for k, v in sorted(status_counts.items()))}")
        return "\n".join(lines)

    def _update_match(order, fields: dict) -> str:
        product_index = int(fields.get("product_index", -1))
        new_product_code = str(fields.get("new_product_code", ""))
        if product_index < 0 or not new_product_code:
            return "Error: fields 需要 product_index (int) 和 new_product_code (string)"

        from models import Product
        from sqlalchemy.orm.attributes import flag_modified

        match_results = list(order.match_results or [])
        products = order.products or []
        if product_index >= len(products):
            return f"Error: product_index {product_index} 超出范围 (共 {len(products)} 个产品)"

        target_mr, target_idx = None, None
        for i, mr in enumerate(match_results):
            idx = mr.get("index", mr.get("product_index", i))
            if idx == product_index:
                target_mr, target_idx = mr, i
                break

        product_name = products[product_index].get("product_name") or products[product_index].get("description") or f"产品#{product_index}"

        if new_product_code.strip().lower() == "unmatch":
            if target_mr is not None:
                old_code = (target_mr.get("matched_product") or {}).get("code", "-")
                match_results[target_idx]["match_status"] = "not_matched"
                match_results[target_idx]["matched_product"] = None
                match_results[target_idx]["match_reason"] = "手动标记为未匹配"
                result_msg = f"已将产品 #{product_index} ({product_name}) 从匹配 {old_code} 改为**未匹配**"
            else:
                return f"产品 #{product_index} ({product_name}) 已是未匹配状态"
        else:
            db_product = ctx.db.query(Product).filter(Product.code == new_product_code.strip()).first()
            if not db_product:
                db_product = ctx.db.query(Product).filter(Product.code.ilike(f"%{new_product_code.strip()}%")).first()
            if not db_product:
                return f"Error: 找不到 code='{new_product_code}'。请先用 search_product_database 搜索。"
            new_matched = {
                "id": db_product.id, "code": db_product.code,
                "product_name_en": db_product.product_name_en, "product_name_jp": db_product.product_name_jp,
                "price": float(db_product.price) if db_product.price else None, "currency": db_product.currency,
                "unit": db_product.unit, "pack_size": db_product.pack_size, "supplier_id": db_product.supplier_id,
            }
            if target_mr is not None:
                old_code = (target_mr.get("matched_product") or {}).get("code", "-")
                match_results[target_idx].update({"match_status": "matched", "matched_product": new_matched, "match_reason": "手动修改"})
                result_msg = f"已将产品 #{product_index} ({product_name}) 改为匹配 {db_product.code} ({db_product.product_name_en})"
            else:
                match_results.append({"index": product_index, "product_name": product_name, "match_status": "matched", "matched_product": new_matched, "match_reason": "手动添加"})
                result_msg = f"已为产品 #{product_index} ({product_name}) 添加匹配: {db_product.code}"

        order.match_results = match_results
        flag_modified(order, "match_results")
        matched = sum(1 for r in match_results if r.get("match_status") == "matched")
        possible = sum(1 for r in match_results if r.get("match_status") == "possible_match")
        not_matched = sum(1 for r in match_results if r.get("match_status") == "not_matched")
        total = matched + possible + not_matched
        rate = round(matched / total * 100, 1) if total > 0 else 0
        order.match_statistics = {"matched": matched, "possible": possible, "not_matched": not_matched, "total": total, "match_rate": rate}
        flag_modified(order, "match_statistics")
        try:
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 保存失败: {e}"
        return f"{result_msg}\n\n统计: matched={matched}, possible={possible}, not_matched={not_matched}, 匹配率={rate}%"

    # ── Consolidated tool ──

    @registry.tool(
        description=(
            "订单管理工具。通过 action 参数选择操作:\n"
            "- overview: 查看订单概览（基本信息、匹配统计、询价状态）\n"
            "- products: 查看订单所有产品及匹配状态（支持 status_filter 过滤）\n"
            "- update_match: 修改产品匹配结果（指定 product_index + new_product_code）\n\n"
            "示例:\n"
            '  manage_order(action="overview", order_id=123)\n'
            '  manage_order(action="products", order_id=123, fields=\'{"status_filter": "not_matched"}\')\n'
            '  manage_order(action="update_match", order_id=123, fields=\'{"product_index": 3, "new_product_code": "ABC123"}\')\n'
            '  manage_order(action="update_match", order_id=123, fields=\'{"product_index": 3, "new_product_code": "unmatch"}\')'
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "操作类型: overview | products | update_match",
            },
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "fields": {
                "type": "STRING",
                "description": "JSON 格式的额外参数 (products: status_filter; update_match: product_index + new_product_code)",
                "required": False,
            },
        },
        group="business",
    )
    def manage_order(action: str = "", order_id: int = 0, fields: str = "{}") -> str:
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
        ctx.register_order(order_id)

        try:
            parsed_fields = json.loads(fields) if fields and fields != "{}" else {}
        except (json.JSONDecodeError, TypeError):
            parsed_fields = {}

        if action == "overview":
            return _overview(order)
        elif action == "products":
            return _products(order, parsed_fields.get("status_filter", ""))
        elif action == "update_match":
            return _update_match(order, parsed_fields)
        else:
            return f"Error: 未知 action '{action}'。支持: overview, products, update_match"
