"""
Clarification Tool — structured "ask the user" mechanism.

DeerFlow equivalent: ask_clarification built-in tool + ClarificationMiddleware.

When the agent is uncertain, it calls this tool instead of producing
a text question. The ClarificationMiddleware then intercepts the result
and triggers a HITL pause, ensuring the user sees a structured
clarification UI (not just text).
"""

from __future__ import annotations

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "ask_clarification": ToolMetaInfo(
        display_name="请求澄清",
        group="utility",
        description="当信息不足时，向用户提出结构化问题",
        prompt_description="向用户提出澄清问题（会暂停执行等待回复）",
        summary="向用户提问",
    ),
}


def register(registry, ctx):
    """Register the ask_clarification tool."""

    @registry.tool(
        description=(
            "当你不确定用户意图或缺少关键信息时，使用此工具向用户提出明确的问题。"
            "调用后会暂停执行，等待用户回复后继续。\n"
            "注意：只在真正需要澄清时使用，不要用于确认操作（那个用 request_confirmation）。"
        ),
        parameters={
            "question": {
                "type": "STRING",
                "description": "要问用户的问题，应该简洁明确",
            },
            "options": {
                "type": "STRING",
                "description": "可选的选项列表（JSON 数组格式），如 '[\"选项A\", \"选项B\"]'。留空则为开放式问题。",
            },
        },
        group="utility",
    )
    def ask_clarification(question: str, options: str = "") -> str:
        import json

        parsed_options = []
        if options:
            try:
                parsed_options = json.loads(options)
                if not isinstance(parsed_options, list):
                    parsed_options = []
            except (json.JSONDecodeError, TypeError):
                parsed_options = []

        # The actual pause is handled by ClarificationMiddleware.after_tool
        # We just return a formatted message for the conversation history
        if parsed_options:
            opts_text = "\n".join(f"  {i+1}. {opt}" for i, opt in enumerate(parsed_options))
            return f"[等待用户回复]\n问题: {question}\n选项:\n{opts_text}"
        return f"[等待用户回复]\n问题: {question}"
