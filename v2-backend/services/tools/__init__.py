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
CORE_TOOLS = {
    "think", "query_db", "get_db_schema", "get_order_overview",
    "calculate", "get_current_time", "ask_clarification",
    "request_confirmation", "modify_excel",
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
    try:
        from services.tools.data_upload import has_upload_context as _has_data_upload
        if _has_data_upload(ctx) or bool(getattr(ctx, 'file_bytes', None)):
            from services.tools.data_upload import create_data_upload_tools
            create_data_upload_tools(registry, ctx)
    except Exception:
        pass

    # ── Deferred: everything not in CORE_TOOLS ──────────────
    # DeerFlow pattern: tools never "disappear", they're just deferred.
    # Agent uses tool_search to activate them on demand.
    for name in list(registry.names()):
        if name not in CORE_TOOLS:
            registry.defer(name)

    return registry


def _auto_register_module(module_path: str, registry, ctx):
    """Import and register a tool module."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        mod.register(registry, ctx)
    except Exception:
        pass
