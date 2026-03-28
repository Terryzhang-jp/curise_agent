"""
Skill 系统 — 可复用的 prompt 模板

State is held in ToolContext, not module globals.
Two trigger methods:
1. User slash commands: /code-review path/to/file.py
2. Agent tool call: use_skill
"""

from pathlib import Path
from services.agent.tool_context import _expand_template
from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "use_skill": ToolMetaInfo(
        display_name="使用技能",
        group="skill",
        description="调用可复用的 prompt 模板技能",
        prompt_description="调用技能模板",
        summary="调用技能",
    ),
}


def register(registry, ctx=None):
    """注册 use_skill 工具到 ToolRegistry"""
    if ctx is None:
        from services.agent.tool_context import ToolContext
        ctx = ToolContext()

    @registry.tool(
        description=(
            "调用可复用的技能模板。技能提供特定场景的工作流指令（如数据上传、询价生成）。"
            "查看系统 prompt 中的 Available Skills 获取可用技能列表。"
        ),
        parameters={
            "skill_name": {
                "type": "STRING",
                "description": "技能名称（如 'query-data'、'generate-inquiry'）",
            },
            "arguments": {
                "type": "STRING",
                "description": "传给技能模板的参数（替换 $ARGUMENTS 占位符）",
                "required": False,
            },
        },
        group="skill",
    )
    def use_skill(skill_name: str, arguments: str = "") -> str:
        skill = ctx.skills.get(skill_name)
        if skill is None:
            available = ", ".join(ctx.skills.keys()) if ctx.skills else "(none)"
            return f"Error: skill '{skill_name}' not found. Available: {available}"

        expanded = _expand_template(skill.body, arguments)

        if skill.references_dir:
            try:
                ref_files = [f.name for f in Path(skill.references_dir).iterdir() if f.is_file()]
                if ref_files:
                    expanded += (
                        "\n\n## Reference Files Available\n"
                        + "\n".join(
                            f"- `{skill.references_dir}/{f}`" for f in sorted(ref_files)
                        )
                        + "\n\nYou can read these files with `read_file` for additional context."
                    )
            except OSError:
                pass

        return expanded
