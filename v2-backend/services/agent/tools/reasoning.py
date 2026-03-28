"""reasoning 组工具 — think (issues-driven continuation pattern)

Architecture:
  - think() accepts structured thought with optional issues list
  - If issues are found, return message forces agent to act on them before proceeding
  - If no issues, return message permits save/completion
  - The LLM decides WHAT to check and WHAT issues exist (generalized, not hardcoded)
  - The return message drives BEHAVIOR (must fix vs. may proceed)
"""

import json
import re

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "think": ToolMetaInfo(
        display_name="思考推理",
        group="reasoning",
        description="结构化思考与质量审查 — 发现问题时返回必须修复的任务队列",
        prompt_description="内部思考和规划，发现问题时自动驱动修复循环",
        summary="思考",
    ),
}


def _extract_issues(thought: str) -> list[str]:
    """Extract issues from thought text heuristically.

    Looks for common patterns that indicate the agent found a problem:
    - Lines starting with "- 问题:", "- ⚠", "- ISSUE:", "- TODO:", "- 修复:"
    - Lines containing "可能出错", "为空", "缺失", "None", "missing", "error"
      in the context of problem identification (section 3)
    """
    issues = []

    # Pattern 1: Explicit issue markers
    for line in thought.split("\n"):
        stripped = line.strip().lstrip("- ").lstrip("* ")
        if not stripped:
            continue
        # Explicit markers
        if re.match(r"^(问题|ISSUE|TODO|修复|FIX|WARNING|⚠)", stripped, re.IGNORECASE):
            issues.append(stripped)
            continue

    # Pattern 2: Look for "潜在问题" section content
    in_problem_section = False
    for line in thought.split("\n"):
        stripped = line.strip()
        if "潜在问题" in stripped or "potential" in stripped.lower() or "问题检测" in stripped:
            in_problem_section = True
            continue
        if in_problem_section:
            # End of section
            if stripped.startswith("(") and not stripped.startswith("(潜"):
                in_problem_section = False
                continue
            if stripped.startswith("- ") or stripped.startswith("* "):
                content = stripped.lstrip("- ").lstrip("* ")
                # Only count if it describes an actual problem (not "no issues")
                if content and not re.search(r"(无问题|没问题|正常|no issue|all good|pass)", content, re.IGNORECASE):
                    issues.append(content)

    return issues


def register(registry, ctx=None):
    """注册 reasoning 组工具 — issues-driven continuation"""

    @registry.tool(
        description=(
            "质量检查点工具。在生成文件、执行关键操作后调用，用于检测问题并驱动修复。\n\n"
            "这不是一个思考工具 — 它是一个检查点。你在内部思考后，用这个工具提交检查结果。\n\n"
            "## 何时必须调用\n"
            "- 生成 Excel/PDF 等文件后\n"
            "- 执行批量数据操作后\n"
            "- 任何需要质量把关的节点\n\n"
            "## thought 参数格式\n"
            "列出检查项和发现的问题。每个问题以「- 问题:」开头：\n"
            "```\n"
            "质量检查:\n"
            "- 产品数: 50个已写入，匹配\n"
            "- 货币: None，已标记为TBD\n"
            "- 问题: 3个产品unit_price为None，公式会出错\n"
            "- 问题: 未设置数字格式\n"
            "```\n\n"
            "## 返回值含义\n"
            "- 返回「⚠ ISSUES」→ 你必须修复每个问题后再次调用 think\n"
            "- 返回「✓ 无待修复问题」→ 可以继续下一步\n\n"
            "不要跳过修复直接交付。think 返回的问题是必须完成的任务。"
        ),
        parameters={
            "thought": {
                "type": "STRING",
                "description": "结构化思考内容（必须包含目标、已完成、问题检测、下一步）",
            }
        },
        group="reasoning",
    )
    def think(thought: str) -> str:
        """Agent 思考工具 — 自动检测 issues 并驱动修复循环"""
        issues = _extract_issues(thought)

        if issues:
            issues_text = "\n".join(f"  [{i+1}] {issue}" for i, issue in enumerate(issues))
            return (
                f"[Thought recorded — {len(issues)} issue(s) detected]\n"
                f"⚠ ISSUES REQUIRING ACTION:\n{issues_text}\n\n"
                f"你必须修复上述每个问题后，再次调用 think 确认问题已清除。"
                f"在所有问题修复前，不要调用 save 或向用户交付结果。"
            )
        else:
            return (
                "[Thought recorded — no issues detected]\n"
                "✓ 无待修复问题，可以继续下一步（验证或交付）。"
            )
