"""
Clarification Middleware — DeerFlow-aligned structured pause mechanism.

When the agent calls `ask_clarification`, this middleware intercepts it
and triggers a structured pause (HITL) instead of continuing the conversation.

This creates a proper "pause and wait for user" flow in chat mode,
rather than the agent producing a text question and continuing.
"""

from __future__ import annotations

import logging
from typing import Any

from services.agent.hooks import Middleware

logger = logging.getLogger(__name__)


class ClarificationMiddleware(Middleware):
    """Intercept ask_clarification tool calls and trigger HITL pause."""

    def after_tool(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        """After ask_clarification executes, set the pause flag on ctx."""
        if tool_name != "ask_clarification":
            return result

        question = args.get("question", "")

        # Set HITL pause — engine will detect this and break the loop
        ctx.should_pause = True
        ctx.pause_reason = f"需要用户澄清: {question}"
        ctx.pause_data = {
            "type": "clarification",
            "question": question,
            "options": args.get("options", []),
        }

        logger.info("ClarificationMiddleware: pausing for user input — %s", question[:100])
        return result
