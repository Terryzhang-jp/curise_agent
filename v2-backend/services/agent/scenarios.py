"""
Scenario-based tool scoping + intent detection.

Reduces LLM tool choice space from 18+ to 5-8 per scenario,
improving accuracy and reducing token waste.
"""

from __future__ import annotations

import re

# ─── Scenario → allowed tool names ───────────────────────────

# Common tools available in ALL scenarios (DeerFlow: built-in tools pattern)
_COMMON_TOOLS = {"think", "calculate", "get_current_time", "request_confirmation", "ask_clarification", "modify_excel"}

SCENARIO_TOOL_GROUPS: dict[str, set[str]] = {
    "inquiry": {
        "get_order_overview", "check_inquiry_readiness", "fill_inquiry_gaps",
        "generate_inquiries", "modify_excel", "query_db", "get_db_schema",
    } | _COMMON_TOOLS,
    "data_upload": {
        "parse_file", "analyze_columns", "prepare_upload", "execute_upload",
        "create_references", "rollback_batch", "query_db", "get_db_schema",
    } | _COMMON_TOOLS,
    "fulfillment": {
        "get_order_fulfillment", "update_order_fulfillment",
        "record_delivery_receipt", "attach_order_file",
        "query_db", "get_db_schema",
    } | _COMMON_TOOLS,
    "query": {
        "query_db", "get_db_schema", "get_order_overview",
    } | _COMMON_TOOLS,
}


def resolve_tools_for_scenario(
    scenario: str | None,
    enabled_tools: set[str] | None,
) -> set[str] | None:
    """Scope tools to those relevant for the given scenario.

    The scenario defines which tools are needed for the task. DB-enabled tools
    that fall outside the scenario are excluded, but scenario-required tools
    are always included (even if not in DB config — they may be newly added).

    Args:
        scenario: Detected or user-specified scenario name.
        enabled_tools: Currently enabled tools from DB config (None = all).

    Returns:
        Scoped tool set, or None if no scoping applies (backward compatible).
    """
    if not scenario or scenario not in SCENARIO_TOOL_GROUPS:
        return enabled_tools  # No scoping — current behavior

    allowed = SCENARIO_TOOL_GROUPS[scenario]

    if enabled_tools is None:
        return allowed  # No DB config — use scenario tools directly

    # Scenario tools always included (they define what this task needs).
    # Also include any DB-enabled tools that overlap with the scenario set
    # (handles tools that exist in both DB config and scenario).
    return allowed.copy()


# ─── Intent detection (regex-based, fast) ─────────────────────

_INTENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(生成|创建|做|发).*(询价|报价|inquiry)", re.IGNORECASE), "inquiry"),
    (re.compile(r"(上传|导入|import).*(产品|报价单|价格表|数据)", re.IGNORECASE), "data_upload"),
    (re.compile(r"(履约|交货|发票|付款|fulfillment|delivery|invoice)", re.IGNORECASE), "fulfillment"),
    (re.compile(r"(查询|统计|多少|列出|分析|比较|汇总|查一下|看看|有哪些)", re.IGNORECASE), "query"),
]


def detect_intent(user_message: str, has_file: bool = False) -> str | None:
    """Detect scenario from user message via keyword matching.

    Args:
        user_message: The user's message text.
        has_file: Whether a file was attached.

    Returns:
        Scenario name or None if no match.
    """
    # File + upload keywords → data_upload (high confidence)
    if has_file:
        upload_kw = re.compile(r"(上传|导入|import|价格|报价|产品)", re.IGNORECASE)
        if upload_kw.search(user_message):
            return "data_upload"

    # Pattern matching
    for pattern, scenario in _INTENT_PATTERNS:
        if pattern.search(user_message):
            return scenario

    return None
