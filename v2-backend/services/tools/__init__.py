"""
Tools package.

Provides create_order_processing_registry() and
create_chat_registry() (general-purpose tools + business tools).
"""

from __future__ import annotations


def create_order_processing_registry(ctx):
    """Create a ToolRegistry for order processing (query_db + think).

    Args:
        ctx: ToolContext instance with db session.

    Returns:
        ToolRegistry with order query + think tools.
    """
    from services.agent.tool_registry import ToolRegistry
    from services.tools.order_query import create_order_query_tools

    registry = ToolRegistry()
    create_order_query_tools(registry, ctx)

    @registry.tool(
        description="记录思考过程，用来分析信息、制定计划、反思结果。",
        parameters={
            "thought": {"type": "STRING", "description": "思考内容"},
        },
    )
    def think(thought: str = "") -> str:
        return "[Thought recorded]"

    return registry


def create_chat_registry(ctx, enabled_tools: set[str] | None = None):
    """Create a ToolRegistry for chat — business tools + safe general-purpose tools.

    Args:
        ctx: ToolContext instance with db session.
        enabled_tools: If provided, only register tools whose names are in this set.
                       If None, register all default tools (backward compatible).

    Returns:
        ToolRegistry with chat-safe tools registered.
    """
    from services.agent.tool_registry import ToolRegistry
    from services.tools.order_query import create_order_query_tools
    from services.agent.tools import reasoning, utility, todo, skill

    registry = ToolRegistry()

    def _should_register(tool_name: str) -> bool:
        return enabled_tools is None or tool_name in enabled_tools

    # Business tools (get_db_schema + query_db)
    if _should_register("query_db") or _should_register("get_db_schema"):
        create_order_query_tools(registry, ctx)

    # Reasoning: think
    if _should_register("think"):
        reasoning.register(registry, ctx)

    # Utility: calculate, get_current_time
    if _should_register("calculate") or _should_register("get_current_time"):
        utility.register(registry, ctx)

    # Todo: todo_write, todo_read
    if _should_register("todo_write") or _should_register("todo_read"):
        todo.register(registry, ctx)

    # Skill: use_skill
    if _should_register("use_skill"):
        skill.register(registry, ctx)

    # Order overview
    if _should_register("get_order_overview"):
        _register_order_overview(registry, ctx)

    # Order inquiry generation
    if _should_register("generate_order_inquiry"):
        _register_order_inquiry(registry, ctx)

    # Fulfillment lifecycle tools
    if _should_register("get_order_fulfillment") or _should_register("update_order_fulfillment") \
       or _should_register("record_delivery_receipt") or _should_register("attach_order_file"):
        from services.tools.fulfillment import create_fulfillment_tools
        create_fulfillment_tools(registry, ctx)

    # Optional tools — only registered when explicitly in enabled_tools set
    if enabled_tools is not None and ("web_fetch" in enabled_tools or "web_search" in enabled_tools):
        from services.agent.tools import web
        web.register(registry, ctx)

    if enabled_tools is not None and "search_product_database" in enabled_tools:
        _register_product_search(registry, ctx)

    # Post-registration filter: remove tools not in enabled_tools
    # This handles cases where group-level registration bundles multiple tools
    # (e.g., utility.register adds both calculate and get_current_time)
    if enabled_tools is not None:
        registered = registry.names()
        for name in registered:
            if name not in enabled_tools:
                registry.remove(name)

    # Product upload tools — auto-registered when file is attached OR when
    # a previous upload session state exists (bypasses enabled_tools filter)
    _has_upload_context = bool(ctx.file_bytes)
    if not _has_upload_context and ctx.pipeline_session_id:
        from services.tools.product_upload import load_upload_state
        _has_upload_context = load_upload_state(ctx.pipeline_session_id) is not None
    if _has_upload_context:
        from services.tools.product_upload import create_product_upload_tools
        create_product_upload_tools(registry, ctx)

    return registry


def _register_order_overview(registry, ctx):
    """Register a tool to get a human-readable order overview."""
    import json

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

        return "\n".join(lines)


def _register_product_search(registry, ctx):
    """Register a lightweight product search tool for chat context."""
    import json
    from sqlalchemy import text

    @registry.tool(
        description="按关键词搜索产品数据库，返回匹配的产品列表（品名、代码、价格、供应商等）",
        parameters={
            "keyword": {
                "type": "STRING",
                "description": "搜索关键词（产品名、代码、品牌等）",
            },
            "limit": {
                "type": "NUMBER",
                "description": "返回数量上限（默认 20）",
                "required": False,
            },
        },
        group="business",
    )
    def search_product_database(keyword: str = "", limit: int = 20) -> str:
        if not keyword.strip():
            return "Error: 请提供搜索关键词"
        limit = min(int(limit), 50)
        kw = f"%{keyword.strip()}%"
        try:
            sql = text("""
                SELECT id, product_name_en, product_name_jp, code, brand,
                       unit, price, currency, pack_size, country_of_origin
                FROM products
                WHERE product_name_en ILIKE :kw
                   OR product_name_jp ILIKE :kw
                   OR code ILIKE :kw
                   OR brand ILIKE :kw
                ORDER BY product_name_en
                LIMIT :lim
            """)
            rows = ctx.db.execute(sql, {"kw": kw, "lim": limit}).fetchall()
            columns = ["id", "product_name_en", "product_name_jp", "code", "brand",
                        "unit", "price", "currency", "pack_size", "country_of_origin"]
            results = []
            for row in rows:
                d = dict(zip(columns, row))
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        d[k] = v.isoformat()
                    elif not isinstance(v, (float, int, bool, str)) and v is not None:
                        d[k] = str(v)
                results.append(d)
            return json.dumps({"results": results, "total": len(results)}, ensure_ascii=False, default=str)
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 产品搜索失败 — {str(e)}"


def _register_order_inquiry(registry, ctx):
    """Register a tool to generate inquiry Excel files for an order."""
    import json
    from config import settings

    UPLOAD_DIR = settings.UPLOAD_DIR

    @registry.tool(
        description="为指定订单生成询价 Excel 文件（按供应商分组，使用供应商模板）。返回生成的文件列表。",
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID（v2_orders 表的 id）",
            },
        },
        group="business",
    )
    def generate_order_inquiry(order_id: int = 0) -> str:
        if not order_id:
            return "Error: 请提供 order_id"
        order_id = int(order_id)

        from models import Order
        order = ctx.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"
        if order.status != "ready":
            return f"Error: 订单状态为 {order.status}，需要 ready 才能生成询价单"
        if not order.match_results:
            return "Error: 没有匹配结果，无法生成询价单"

        from services.inquiry_agent import run_inquiry_agent
        try:
            result = run_inquiry_agent(order, ctx.db)
            order.inquiry_data = result
            ctx.db.commit()
        except Exception as e:
            ctx.db.rollback()
            return f"Error: 生成失败 — {str(e)}"

        files = result.get("generated_files", [])
        success = [f for f in files if f.get("filename")]
        errors = [f for f in files if f.get("error")]

        lines = [f"询价单生成完成: {len(success)} 份成功, {len(errors)} 份失败"]
        for f in success:
            lines.append(f"  供应商 #{f['supplier_id']}: {f['filename']} ({f['product_count']} 个产品)")
        for f in errors:
            lines.append(f"  供应商 #{f['supplier_id']}: 失败 — {f['error']}")
        if result.get("unassigned_count", 0) > 0:
            lines.append(f"  未分配产品: {result['unassigned_count']} 个")

        return "\n".join(lines)


