"""
Tools package — DeerFlow-aligned tool loading.

Architecture (post-refactor):
  - ALL tools are always registered (no scenario whitelist filtering)
  - Core tools: always visible to LLM
  - Extended tools: registered but deferred (activated via tool_search)
  - Scenario detection: only affects system prompt, NOT tool list
  - This eliminates the class of bugs where tools "disappear" based on
    intent detection accuracy

Provides create_order_processing_registry() and create_chat_registry().
"""

from __future__ import annotations


def create_order_processing_registry(ctx):
    """Create a ToolRegistry for order processing (query_db + think)."""
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


# Core tools: always visible to LLM (never deferred)
# `use_skill` is the foundational skill-orchestration mechanism — without it
# always being visible, no skill can ever invoke another skill (the LLM would
# not even know `use_skill` exists in its tool schema).
CORE_TOOLS = {
    "think", "query_db", "get_db_schema", "manage_order",
    "calculate", "get_current_time", "ask_clarification",
    "request_confirmation", "modify_excel",
    "use_skill",
}


def create_chat_registry(ctx, enabled_tools: set[str] | None = None,
                         chat_storage=None, session_id: str | None = None):
    """Create a ToolRegistry for chat.

    DeerFlow-aligned: ALL tools are always registered.
    enabled_tools parameter is IGNORED for registration (kept for API compat).
    Only affects which tools are deferred vs active.
    """
    from services.agent.tool_registry import ToolRegistry

    registry = ToolRegistry()

    # ── Register ALL business tools (no filtering) ──────────
    _auto_register_module("services.tools.order_query", registry, ctx)
    _auto_register_module("services.tools.order_overview", registry, ctx)
    _auto_register_module("services.tools.order_extraction", registry, ctx)
    _auto_register_module("services.tools.order_matching", registry, ctx)
    _auto_register_module("services.tools.document_order", registry, ctx)
    _auto_register_module("services.tools.fulfillment", registry, ctx)
    _auto_register_module("services.tools.inquiry_workflow", registry, ctx)

    # ── Register ALL general-purpose tools ───────────────────
    from services.agent.tools import reasoning, utility, todo, skill, shell
    reasoning.register(registry, ctx)
    utility.register(registry, ctx)
    todo.register(registry, ctx)
    skill.register(registry, ctx)
    shell.register(registry, ctx)

    # Clarification tool
    from services.agent.tools.clarification import register as reg_clarification
    reg_clarification(registry, ctx)

    # Excel modification tool
    from services.agent.tools.excel import register as reg_excel
    reg_excel(registry, ctx)

    # Confirmation tool
    from services.tools.confirmation import create_confirmation_tools
    create_confirmation_tools(registry, ctx)

    # Data upload tools (conditional: only when file context exists)
    # Internal tools are registered but will be deferred — manage_upload routes to them.
    try:
        from services.tools.data_upload import has_upload_context as _has_data_upload
        if _has_data_upload(ctx) or bool(getattr(ctx, 'file_bytes', None)):
            from services.tools.data_upload import create_data_upload_tools
            create_data_upload_tools(registry, ctx)
            # Add routing wrappers (parse_upload + manage_upload) that call internal tools
            _register_upload_wrappers(registry, ctx)
    except Exception:
        pass

    # ── Deferred: everything not in CORE_TOOLS ──────────────
    # DeerFlow pattern: tools never "disappear", they're just deferred.
    # Agent uses tool_search to activate them on demand.
    # Internal upload tools are always deferred (accessed via manage_upload routing).
    _INTERNAL_UPLOAD_TOOLS = {
        "parse_file", "analyze_columns", "resolve_and_validate",
        "create_references", "preview_changes", "execute_upload",
        "prepare_upload", "rollback_batch", "audit_data",
    }
    # Old tool names that have been consolidated (defer even if in CORE_TOOLS)
    _CONSOLIDATED_OLD_NAMES = {
        "get_order_overview", "get_order_products", "update_match_result",
        "get_order_fulfillment", "update_order_fulfillment",
        "record_delivery_receipt", "attach_order_file",
        "check_inquiry_readiness", "fill_inquiry_gaps", "generate_inquiries",
        "read_file", "write_file", "list_files", "edit_file",
        "todo_write", "todo_read",
    }
    for name in list(registry.names()):
        if name not in CORE_TOOLS or name in _CONSOLIDATED_OLD_NAMES:
            registry.defer(name)
    # Internal upload tools: always deferred (sub-agents access them directly)
    for name in _INTERNAL_UPLOAD_TOOLS:
        if name in registry.names():
            registry.defer(name)

    return registry


def _register_upload_wrappers(registry, ctx):
    """Register parse_upload + manage_upload routing wrappers over internal upload tools."""
    import json

    @registry.tool(
        description=(
            "解析上传的 Excel/CSV 文件，创建暂存数据。这是数据上传流程的入口。\n"
            "解析后使用 manage_upload(action='prepare') 进行验证和预览。"
        ),
        parameters={
            "column_mapping": {
                "type": "STRING",
                "description": "JSON 列映射 (可选, 如 {'A': 'product_name', 'B': 'price'})",
                "required": False,
            },
        },
        group="data_upload",
    )
    def parse_upload(column_mapping: str = "{}") -> str:
        if "parse_file" in registry.names():
            return registry.execute("parse_file", {"column_mapping": column_mapping})
        return "Error: parse_file 工具未注册（需要上传文件）"

    @registry.tool(
        description=(
            "产品上传管理工具。通过 action 选择操作:\n"
            "- prepare: 一键验证+审计+预览 ⭐ 主入口 (解析后直接调这个)\n"
            "- execute: 确认后执行导入\n"
            "- rollback: 回滚已完成的批次\n"
            "- preview: 单独预览变更\n"
            "- analyze: 分析未映射列\n"
            "- audit: 数据质量审计\n"
            "- create_refs: 创建缺失的引用数据\n\n"
            "流程: parse_upload → manage_upload(prepare) → 用户确认 → manage_upload(execute)\n\n"
            "示例:\n"
            '  manage_upload(action="prepare", batch_id=5)\n'
            '  manage_upload(action="execute", batch_id=5)\n'
            '  manage_upload(action="rollback", batch_id=5)'
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "操作: prepare | execute | rollback | preview | analyze | audit | create_refs",
            },
            "batch_id": {
                "type": "NUMBER",
                "description": "批次 ID (从 parse_upload 返回值获取)",
                "required": False,
            },
        },
        group="data_upload",
    )
    def manage_upload(action: str = "", batch_id: int = 0) -> str:
        if not action:
            return "Error: 需要 action"
        action_map = {
            "prepare": "prepare_upload",
            "execute": "execute_upload",
            "rollback": "rollback_batch",
            "preview": "preview_changes",
            "analyze": "analyze_columns",
            "audit": "audit_data",
            "create_refs": "create_references",
        }
        internal_name = action_map.get(action)
        if not internal_name:
            return f"Error: 未知 action '{action}'。支持: {', '.join(action_map.keys())}"
        if internal_name not in registry.names():
            return f"Error: {internal_name} 工具未注册"
        args = {}
        if batch_id:
            args["batch_id"] = int(batch_id)
        return registry.execute(internal_name, args)


def _auto_register_module(module_path: str, registry, ctx):
    """Import and register a tool module."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        mod.register(registry, ctx)
    except Exception:
        pass
