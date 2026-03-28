"""request_confirmation — agent asks user before impactful operations."""
import json

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "request_confirmation": ToolMetaInfo(
        display_name="请求确认",
        group="utility",
        description="执行重要操作前请求用户确认",
        prompt_description="请求用户确认（重要操作前必须调用）",
        summary="请求用户确认",
    ),
}


def register(registry, ctx=None):
    """Auto-discovery compatible alias."""
    create_confirmation_tools(registry, ctx)


def create_confirmation_tools(registry, ctx):
    @registry.tool(
        description="请求用户确认。在执行重要或不可逆操作前调用此工具。调用后停止，等待用户回复。",
        parameters={
            "title": {"type": "STRING", "description": "操作标题"},
            "description": {"type": "STRING", "description": "操作内容和影响"},
            "confirm_message": {"type": "STRING", "description": "用户确认时自动发送的消息"},
            "reject_message": {"type": "STRING", "description": "用户取消时自动发送的消息"},
        },
    )
    def request_confirmation(
        title: str = "", description: str = "",
        confirm_message: str = "确认执行", reject_message: str = "取消操作",
    ) -> str:
        text = f"需要确认: {title}\n{description}\n\n等待用户确认..."
        structured = {
            "card_type": "confirmation",
            "title": title,
            "description": description,
            "actions": [
                {"label": "确认", "message": confirm_message, "variant": "default"},
                {"label": "取消", "message": reject_message, "variant": "outline"},
            ],
        }
        return text + "\n__STRUCTURED__\n" + json.dumps(structured, ensure_ascii=False)
