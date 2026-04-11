"""
AgentTracer — token usage + tool performance tracking.

Records LLM calls and tool calls to v2_agent_traces for cost attribution
and performance analysis. All DB writes are best-effort (errors logged, not raised).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# LLM pricing per 1M tokens (USD)
_PRICING = {
    "gemini-3-flash-preview": {"input": 0.15, "output": 0.60, "thinking": 0.70},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "thinking": 0.70},
    "gemini-2.5-flash-preview-05-20": {"input": 0.15, "output": 0.60, "thinking": 0.70},
    "kimi-k2.5": {"input": 0.60, "output": 2.50, "thinking": 0.00},
    "kimi-k2": {"input": 0.80, "output": 3.00, "thinking": 0.00},
}

# Default pricing for unknown models
_DEFAULT_PRICING = {"input": 0.15, "output": 0.60, "thinking": 0.70}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int,
                   thinking_tokens: int = 0) -> float:
    """Estimate cost in USD based on token counts."""
    pricing = _PRICING.get(model, _DEFAULT_PRICING)
    cost = (
        prompt_tokens * pricing["input"] / 1_000_000
        + completion_tokens * pricing["output"] / 1_000_000
        + thinking_tokens * pricing["thinking"] / 1_000_000
    )
    return round(cost, 6)


class AgentTracer:
    """Records execution traces to v2_agent_traces."""

    def __init__(self, db: Any, session_id: str):
        self._db = db
        self._session_id = session_id

    def record_llm_call(
        self,
        turn: int,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        thinking_tokens: int = 0,
    ):
        """Record an LLM API call. Best-effort — never raises."""
        try:
            from core.models import AgentTrace
            cost = _estimate_cost(model, prompt_tokens, completion_tokens, thinking_tokens)
            trace = AgentTrace(
                session_id=self._session_id,
                turn_number=turn,
                event_type="llm_call",
                model_name=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                thinking_tokens=thinking_tokens,
                estimated_cost_usd=cost,
            )
            self._db.add(trace)
            self._db.flush()
        except Exception as e:
            logger.debug("AgentTracer.record_llm_call failed: %s", e)

    def record_tool_call(
        self,
        turn: int,
        tool_name: str,
        duration_ms: int,
        success: bool,
        error_msg: str | None = None,
    ):
        """Record a tool execution. Best-effort — never raises."""
        try:
            from core.models import AgentTrace
            trace = AgentTrace(
                session_id=self._session_id,
                turn_number=turn,
                event_type="tool_call",
                tool_name=tool_name,
                tool_duration_ms=duration_ms,
                tool_success=success,
                error_message=error_msg,
            )
            self._db.add(trace)
            self._db.flush()
        except Exception as e:
            logger.debug("AgentTracer.record_tool_call failed: %s", e)

    def get_session_stats(self) -> dict:
        """Aggregate stats for the session."""
        try:
            from core.models import AgentTrace
            from sqlalchemy import func

            traces = self._db.query(AgentTrace).filter(
                AgentTrace.session_id == self._session_id,
            ).all()

            total_prompt = 0
            total_completion = 0
            total_thinking = 0
            total_cost = 0.0
            tool_calls = 0
            tool_errors = 0
            tool_total_ms = 0

            for t in traces:
                if t.event_type == "llm_call":
                    total_prompt += t.prompt_tokens or 0
                    total_completion += t.completion_tokens or 0
                    total_thinking += t.thinking_tokens or 0
                    total_cost += float(t.estimated_cost_usd or 0)
                elif t.event_type == "tool_call":
                    tool_calls += 1
                    tool_total_ms += t.tool_duration_ms or 0
                    if not t.tool_success:
                        tool_errors += 1

            return {
                "session_id": self._session_id,
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_thinking_tokens": total_thinking,
                "total_tokens": total_prompt + total_completion + total_thinking,
                "estimated_cost_usd": round(total_cost, 6),
                "tool_calls": tool_calls,
                "tool_errors": tool_errors,
                "tool_total_duration_ms": tool_total_ms,
                "trace_count": len(traces),
            }
        except Exception as e:
            logger.error("AgentTracer.get_session_stats failed: %s", e)
            return {"session_id": self._session_id, "error": str(e)}
