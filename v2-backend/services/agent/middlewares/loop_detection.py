"""
Loop Detection Middleware — DeerFlow-aligned order-independent hash for detecting repeated tool calls.

Replaces inline loop detection in engine.py with a cleaner middleware approach.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from typing import Any

from services.agent.hooks import Middleware

logger = logging.getLogger(__name__)


class LoopDetectionMiddleware(Middleware):
    """Detect and break tool call loops using order-independent batch hashing.

    Three tiers:
    - warn_threshold: inject a soft warning (once per signature)
    - force_stop_threshold: strip tool calls, force text answer
    """

    def __init__(
        self,
        window: int = 20,
        warn_threshold: int = 3,
        force_stop: int = 5,
    ):
        self._recent: deque[str] = deque(maxlen=window)
        self._warned: set[str] = set()
        self._warn_threshold = warn_threshold
        self._force_stop = force_stop
        # Store recent results for context in warnings
        self._recent_results: dict[str, str] = {}

    def _batch_hash(self, function_calls) -> str:
        """Order-independent hash: sort (name, md5(args)) tuples, then hash."""
        sigs = sorted(
            f"{fc.name}:{hashlib.md5(json.dumps(fc.args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]}"
            for fc in function_calls
            if fc.name != "think"
        )
        if not sigs:
            return ""
        return hashlib.md5("|".join(sigs).encode()).hexdigest()[:12]

    def _call_signature(self, name: str, args: dict) -> str:
        """Single tool call signature for result tracking."""
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False)
        return f"{name}:{hashlib.md5(args_str.encode()).hexdigest()[:8]}"

    def after_model(self, response: Any, ctx: Any) -> Any:
        """Check for loops after each LLM response."""
        if not hasattr(response, 'function_calls') or not response.function_calls:
            return response

        sig = self._batch_hash(response.function_calls)
        if not sig:
            return response

        self._recent.append(sig)
        count = sum(1 for s in self._recent if s == sig)

        if count >= self._force_stop:
            # Hard stop: strip tool_calls, inject forced stop text
            names = [fc.name for fc in response.function_calls]
            logger.warning("LoopDetection: FORCE STOP — %s repeated %d times", names, count)
            response.function_calls = []
            response.text_parts.append(
                f"[FORCED STOP] 工具 {names} 重复调用 {count} 次，已自动终止。请直接给出最终答案。"
            )
        elif count >= self._warn_threshold and sig not in self._warned:
            # Soft warning (single-warn per signature)
            self._warned.add(sig)
            tool_label = response.function_calls[0].name if response.function_calls else "unknown"
            logger.info("LoopDetection: WARN — %s repeated %d times", tool_label, count)
            # Store warning for engine to inject as system message
            response._loop_warning = (
                f"[LOOP WARNING] 检测到 {tool_label} 重复调用模式（{count}次）。"
                "请用 think 分析是否需要换一种方法。"
            )

        return response

    def after_tool(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        """Track tool results for loop context."""
        if tool_name != "think":
            sig = self._call_signature(tool_name, args)
            self._recent_results[sig] = (result or "")[:150]
        return result
