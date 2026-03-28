"""
Error Recovery Middleware — tracks consecutive tool failures and injects recovery guidance.

Prevents the Agent from repeatedly hitting the same error without changing approach.
Enhanced with pattern-specific recovery hints (e.g., JSON vs JSONB).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from services.agent.hooks import Middleware

logger = logging.getLogger(__name__)

# Pattern-specific SQL error recovery hints
_SQL_ERROR_HINTS: list[tuple[re.Pattern, str]] = [
    # JSON vs JSONB type mismatch (the #1 recurring error)
    (
        re.compile(r"jsonb_array_elements\(json\)|function jsonb_\w+\(json\)", re.IGNORECASE),
        "修复方法：该列是 JSON 类型（不是 JSONB）。"
        "请改用 json_array_elements() 替代 jsonb_array_elements()，"
        "或者在列名后加 ::jsonb 强转，例如: jsonb_array_elements(match_results::jsonb)"
    ),
    # Column does not exist
    (
        re.compile(r'column "(\w+)" does not exist', re.IGNORECASE),
        "修复方法：该列名不存在。请先用 get_db_schema 查看正确的列名。"
    ),
    # Relation/table does not exist
    (
        re.compile(r'relation "(\w+)" does not exist', re.IGNORECASE),
        "修复方法：该表名不存在。请先用 get_db_schema 查看可用的表名。"
    ),
    # JSON field extraction on wrong type
    (
        re.compile(r"cannot extract element|cannot call json_array_elements on a scalar", re.IGNORECASE),
        "修复方法：该字段不是 JSON 数组。请先用 LIMIT 1 查看该字段的实际内容和结构。"
    ),
    # Aggregate function misuse
    (
        re.compile(r"must appear in the GROUP BY clause|not in aggregate function", re.IGNORECASE),
        "修复方法：SELECT 中的非聚合列必须出现在 GROUP BY 中。请检查 SELECT 和 GROUP BY 是否匹配。"
    ),
]


class ErrorRecoveryMiddleware(Middleware):
    """Track consecutive tool errors and inject pattern-specific recovery hints."""

    def __init__(self, max_consecutive: int = 2):
        self._error_counts: dict[str, int] = defaultdict(int)
        self._last_error: dict[str, str] = {}
        self._max_consecutive = max_consecutive

    def after_tool(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        if not result:
            return result

        if result.startswith("Error:") or "SQL execution failed" in result:
            self._error_counts[tool_name] += 1
            count = self._error_counts[tool_name]

            # Check for pattern-specific hints (especially SQL errors)
            specific_hint = ""
            if tool_name == "query_db":
                for pattern, hint in _SQL_ERROR_HINTS:
                    if pattern.search(result):
                        specific_hint = f"\n\n[具体修复建议] {hint}"
                        break

                # Detect if same error is repeating
                last = self._last_error.get(tool_name, "")
                if last and _same_error_type(last, result):
                    specific_hint += (
                        "\n\n[警告] 这与上次的错误类型相同。"
                        "请不要再用同样的方式重试。"
                        "用 think 分析错误后，修改 SQL 再执行。"
                    )

            self._last_error[tool_name] = result

            if count >= self._max_consecutive:
                result += (
                    f"\n\n[System] 该工具连续失败 {count} 次。"
                    "建议：(1) 用 think 分析失败模式 (2) 换一种 SQL 写法 (3) 如果无法解决，诚实告知用户。"
                )
                result += specific_hint
                logger.info("ErrorRecovery: %s failed %d times consecutively", tool_name, count)
            elif specific_hint:
                result += specific_hint
        else:
            # Reset on success
            self._error_counts[tool_name] = 0
            self._last_error.pop(tool_name, None)

        return result


def _same_error_type(prev: str, curr: str) -> bool:
    """Check if two errors are of the same type (rough heuristic)."""
    # Extract the core error message (after "Error:" prefix)
    def _extract_core(s: str) -> str:
        for prefix in ("SQL execution failed —", "Error:"):
            idx = s.find(prefix)
            if idx >= 0:
                return s[idx:idx+100]
        return s[:100]

    return _extract_core(prev) == _extract_core(curr)
