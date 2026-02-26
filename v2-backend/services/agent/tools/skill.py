"""
Skill 系统 — 可复用的 prompt 模板

State is held in ToolContext, not module globals.
Two trigger methods:
1. User slash commands: /code-review path/to/file.py
2. Agent tool call: use_skill
"""

from pathlib import Path
from services.agent.tool_context import _expand_template


def register(registry, ctx=None):
    """注册 use_skill 工具到 ToolRegistry"""
    if ctx is None:
        from services.agent.tool_context import ToolContext
        ctx = ToolContext()

    @registry.tool(
        description=(
            "Invoke a reusable skill (prompt template) by name. "
            "Skills provide domain-specific instructions and workflows. "
            "Use `list_skills` argument pattern or check system prompt for available skills."
        ),
        parameters={
            "skill_name": {
                "type": "STRING",
                "description": "Name of the skill to invoke (e.g. 'code-review')",
            },
            "arguments": {
                "type": "STRING",
                "description": "Arguments to substitute into the skill template ($ARGUMENTS placeholder)",
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
