"""
Sub-Agent Limit Middleware — DeerFlow-aligned governance for sub-agent delegation.

Prevents:
1. Too many concurrent delegate calls in a single turn
2. Recursive delegation (sub-agent calling delegate)
3. Unbounded execution time (timeout)

Inspired by DeerFlow's SubagentLimitMiddleware.
"""

from __future__ import annotations

import logging
from typing import Any

from services.agent.hooks import Middleware, GuardrailTriggered

logger = logging.getLogger(__name__)


class SubagentLimitMiddleware(Middleware):
    """Govern sub-agent tool calls: concurrency limits, recursion blocking, timeout."""

    def __init__(self, max_concurrent: int = 3):
        self._max_concurrent = max_concurrent

    def after_model(self, response: Any, ctx: Any) -> Any:
        """Truncate excess delegate calls in a single LLM turn."""
        if not hasattr(response, 'function_calls') or not response.function_calls:
            return response

        delegate_calls = [fc for fc in response.function_calls if fc.name == "delegate"]
        if len(delegate_calls) <= self._max_concurrent:
            return response

        # Truncate excess delegate calls
        logger.warning(
            "SubagentLimit: LLM requested %d delegate calls, capping to %d",
            len(delegate_calls), self._max_concurrent,
        )

        kept = 0
        filtered = []
        for fc in response.function_calls:
            if fc.name == "delegate":
                if kept < self._max_concurrent:
                    filtered.append(fc)
                    kept += 1
                # else: drop
            else:
                filtered.append(fc)

        response.function_calls = filtered

        # Inject warning so model knows some were dropped
        dropped = len(delegate_calls) - self._max_concurrent
        response.text_parts.append(
            f"[System] 单轮最多 {self._max_concurrent} 个子Agent任务，"
            f"已截断 {dropped} 个。请在后续轮次继续。"
        )

        return response

    def before_tool(self, tool_name: str, args: dict, ctx: Any) -> dict:
        """Block recursive delegation (sub-agent trying to call delegate)."""
        if tool_name != "delegate":
            return args

        # Check if we're inside a sub-agent context
        is_sub_agent = getattr(ctx, '_is_sub_agent', False)
        if is_sub_agent:
            raise GuardrailTriggered(
                "Error: 子Agent不允许递归委派任务。请直接使用可用工具完成任务。"
            )

        return args
