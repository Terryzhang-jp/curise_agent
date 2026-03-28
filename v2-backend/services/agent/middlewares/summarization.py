"""
Summarization Middleware — DeerFlow-aligned context reduction.

Extracted from engine.py's inline auto-compact logic into a proper middleware.
Monitors token usage and triggers summarization when thresholds are exceeded.

Triggers:
  - Token count exceeds threshold (configurable)
  - Message count exceeds limit (configurable)
"""

from __future__ import annotations

import logging
from typing import Any

from services.agent.hooks import Middleware

logger = logging.getLogger(__name__)


class SummarizationMiddleware(Middleware):
    """Monitor context size and trigger summarization when needed.

    Works with engine's compact() method — sets a flag on ctx that
    the engine checks after each turn.

    This middleware replaces the inline auto-compact logic in engine.py,
    making the threshold configurable and the logic reusable.
    """

    def __init__(
        self,
        token_threshold: int = 80000,
        message_threshold: int = 40,
    ):
        self._token_threshold = token_threshold
        self._message_threshold = message_threshold
        self._triggered = False  # Only trigger once per run

    def after_model(self, response: Any, ctx: Any) -> Any:
        """Check if summarization should be triggered based on token usage."""
        if self._triggered:
            return response

        # Check token-based threshold
        prompt_tokens = getattr(response, 'prompt_tokens', 0) or 0
        if prompt_tokens >= self._token_threshold:
            ctx._should_compact = True
            self._triggered = True
            logger.info(
                "SummarizationMiddleware: token count (%d) exceeds threshold (%d), flagging for compact",
                prompt_tokens, self._token_threshold,
            )

        return response

    def before_model(self, history: list, ctx: Any) -> list:
        """Check message count threshold."""
        if self._triggered:
            return history

        if len(history) >= self._message_threshold:
            ctx._should_compact = True
            self._triggered = True
            logger.info(
                "SummarizationMiddleware: message count (%d) exceeds threshold (%d), flagging for compact",
                len(history), self._message_threshold,
            )

        return history
