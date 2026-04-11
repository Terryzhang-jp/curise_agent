"""
Product matching tool — Agent-triggered product matching against database.

Wraps the existing run_agent_matching() logic as an Agent-callable tool.
Agent can observe matching results and decide next steps.
"""

from __future__ import annotations

import json
import logging

from services.tools.registry_loader import ToolMetaInfo

logger = logging.getLogger(__name__)

TOOL_META = {
    "match_products": ToolMetaInfo(
        display_name="匹配产品",
        group="business",
        description="将订单产品与数据库匹配 (代码精确匹配 + LLM 模糊匹配)",
        prompt_description="匹配订单产品到产品数据库",
        summary="匹配产品",
    ),
}


def register(registry, ctx=None):
    """Register match_products tool."""

    @registry.tool(
        description=(
            "将订单中的产品与数据库进行匹配。\n"
            "流程: 地理解析 (国家/港口) → 代码精确匹配 → LLM 模糊匹配 (可选)\n\n"
            "返回: 匹配统计 (匹配率、各状态数量) + 未匹配/低置信度产品列表。\n"
            "前提: 订单必须已完成提取 (有 products 数据)。\n\n"
            "示例:\n"
            '  match_products(order_id=123)'
        ),
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID (必须已完成提取)",
            },
        },
        group="business",
    )
    def match_products(order_id: int = 0) -> str:
        if not order_id:
            return "Error: 需要 order_id"
        order_id = int(order_id)

        from models import Order
        from sqlalchemy.orm.attributes import flag_modified
        from services.tools._security import scope_to_owner

        query = ctx.db.query(Order).filter(Order.id == order_id)
        query = scope_to_owner(query, Order, ctx)
        order = query.first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"

        if not order.products or len(order.products) == 0:
            return f"Error: 订单 {order_id} 没有产品数据, 请先提取 (extract_order)"

        # Build extraction data for matching
        extracted = {
            "order_metadata": order.order_metadata or {},
            "products": order.products,
        }

        # Run matching
        order.status = "matching"
        ctx.db.commit()

        try:
            from services.order_processor import run_agent_matching
            import time

            start = time.time()
            match_result = run_agent_matching(order_id, extracted, ctx.db)
            elapsed = time.time() - start

            # Save results
            order.match_results = match_result.get("match_results")
            order.match_statistics = match_result.get("statistics")
            order.country_id = match_result.get("country_id")
            order.port_id = match_result.get("port_id")
            order.delivery_date = match_result.get("delivery_date")

            flag_modified(order, "match_results")
            flag_modified(order, "match_statistics")

            if match_result.get("skipped_reason") == "missing_delivery_date":
                order.status = "ready"
                order.processing_error = "缺少交货日期。请补充后重新匹配。"
                ctx.db.commit()
                return (
                    f"## ⚠️ 匹配跳过 — 缺少交货日期\n"
                    f"订单 {order_id} 没有 delivery_date, 无法按有效期过滤产品。\n"
                    f"请用 manage_order(action='update_match') 补充信息, 或问用户提供交货日期。"
                )

            order.status = "ready"
            order.processing_error = None

            # Auto-run post-matching analysis
            try:
                from services.order_processor import run_financial_analysis
                order.financial_data = run_financial_analysis(order)
            except Exception as e:
                logger.warning("Financial analysis failed: %s", e)

            try:
                from services.inquiry_agent import run_inquiry_pre_analysis
                order.inquiry_data = run_inquiry_pre_analysis(order, ctx.db)
                flag_modified(order, "inquiry_data")
            except Exception as e:
                logger.warning("Inquiry pre-analysis failed: %s", e)

            ctx.db.commit()

            # Build response
            stats = order.match_statistics or {}
            match_results = order.match_results or []

            matched = stats.get("matched", 0)
            possible = stats.get("possible", 0)
            not_matched = stats.get("not_matched", 0)
            total = stats.get("total", len(match_results))
            rate = stats.get("match_rate", 0)

            lines = [
                f"## 匹配完成 — 订单 #{order_id}",
                f"- 耗时: {elapsed:.1f}s",
                f"- 匹配率: {rate}%",
                f"- 已匹配: {matched}",
                f"- 可能匹配: {possible}",
                f"- 未匹配: {not_matched}",
                f"- 总计: {total}",
            ]

            if order.country_id:
                lines.append(f"- 国家 ID: {order.country_id}")
            if order.port_id:
                lines.append(f"- 港口 ID: {order.port_id}")

            # List unmatched / low-confidence products
            problem_items = [
                r for r in match_results
                if r.get("match_status") in ("not_matched", "possible_match")
            ]
            if problem_items:
                lines += ["", f"## 需要注意的产品 ({len(problem_items)} 个)"]
                for p in problem_items[:10]:
                    name = p.get("product_name", "?")[:35]
                    status = p.get("match_status", "?")
                    code = p.get("product_code", "-")
                    lines.append(f"  - [{status}] {code} | {name}")
                if len(problem_items) > 10:
                    lines.append(f"  ... 还有 {len(problem_items) - 10} 个")

            # Inquiry readiness hint
            if order.inquiry_data:
                suppliers = order.inquiry_data.get("suppliers", {})
                ready_count = sum(1 for s in suppliers.values()
                                  if isinstance(s, dict) and s.get("status") != "error")
                lines += ["", f"## 询价就绪", f"- {ready_count} 个供应商可生成询价单"]

            ctx.register_order(order_id)
            return "\n".join(lines)

        except Exception as e:
            logger.error("match_products %d failed: %s", order_id, e, exc_info=True)
            order.status = "error"
            order.processing_error = f"匹配失败: {e}"
            ctx.db.commit()
            return f"Error: 匹配失败: {e}"
