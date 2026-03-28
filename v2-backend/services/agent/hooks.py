"""
Middleware system — unified interception points for security, audit, and guardrails.

Provides 6 lifecycle hooks:
  before_agent  → once at start of run()
  before_model  → before each LLM call
  after_model   → after each LLM call
  before_tool   → before each tool execution (can block)
  after_tool    → after each tool execution
  after_agent   → once at end of run()

Backward compatible: ToolHook (pre_tool_use/post_tool_use) still works.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class GuardrailTriggered(Exception):
    """Raised by a before_tool hook to block tool execution."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


# ============================================================
# Middleware base class — 6 lifecycle hooks
# ============================================================

class Middleware:
    """Base middleware — subclass and override hooks as needed.

    All hooks have sensible no-op defaults. Override only what you need.
    """

    def before_agent(self, user_message: str, ctx: Any) -> str:
        """Called once at the start of run(). Return (possibly modified) user_message."""
        return user_message

    def before_model(self, history: list, ctx: Any) -> list:
        """Called before each LLM call. Return (possibly modified) history."""
        return history

    def after_model(self, response: Any, ctx: Any) -> Any:
        """Called after each LLM call. Return (possibly modified) LLMResponse."""
        return response

    def before_tool(self, tool_name: str, args: dict, ctx: Any) -> dict:
        """Called before tool execution. Return (possibly modified) args.

        Raise GuardrailTriggered to block execution.
        """
        return args

    def after_tool(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        """Called after tool execution. Return (possibly modified) result."""
        return result

    def after_agent(self, final_answer: str, ctx: Any) -> str:
        """Called once at the end of run(). Return (possibly modified) final_answer."""
        return final_answer


# ============================================================
# ToolHook — backward-compatible alias
# ============================================================

class ToolHook(Middleware):
    """Backward-compatible hook base class.

    If you override pre_tool_use/post_tool_use (old API), they will be
    called via before_tool/after_tool automatically. New code should
    subclass Middleware directly and use before_tool/after_tool.
    """

    def before_tool(self, tool_name: str, args: dict, ctx: Any) -> dict:
        return self.pre_tool_use(tool_name, args, ctx)

    def after_tool(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        return self.post_tool_use(tool_name, args, result, ctx)

    def pre_tool_use(self, tool_name: str, args: dict, ctx: Any) -> dict:
        """Old API — override this or before_tool."""
        return args

    def post_tool_use(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        """Old API — override this or after_tool."""
        return result


# ============================================================
# MiddlewareChain — ordered middleware execution
# ============================================================

class MiddlewareChain:
    """Ordered middleware chain. Each lifecycle hook runs all middlewares in order."""

    def __init__(self, middlewares: list[Middleware] | None = None):
        self._middlewares: list[Middleware] = middlewares or []

    def add(self, mw: Middleware):
        self._middlewares.append(mw)

    # --- Lifecycle runners ---

    def run_before_agent(self, user_message: str, ctx: Any) -> str:
        for mw in self._middlewares:
            try:
                user_message = mw.before_agent(user_message, ctx)
            except Exception as e:
                logger.warning("Middleware %s.before_agent failed: %s", type(mw).__name__, e)
        return user_message

    def run_before_model(self, history: list, ctx: Any) -> list:
        for mw in self._middlewares:
            try:
                history = mw.before_model(history, ctx)
            except Exception as e:
                logger.warning("Middleware %s.before_model failed: %s", type(mw).__name__, e)
        return history

    def run_after_model(self, response: Any, ctx: Any) -> Any:
        for mw in self._middlewares:
            try:
                response = mw.after_model(response, ctx)
            except Exception as e:
                logger.warning("Middleware %s.after_model failed: %s", type(mw).__name__, e)
        return response

    def run_before_tool(self, tool_name: str, args: dict, ctx: Any) -> dict:
        """Run all before_tool hooks. Any may raise GuardrailTriggered."""
        for mw in self._middlewares:
            try:
                args = mw.before_tool(tool_name, args, ctx)
            except GuardrailTriggered:
                raise
            except Exception as e:
                logger.warning("Middleware %s.before_tool failed: %s", type(mw).__name__, e)
        return args

    def run_after_tool(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        for mw in self._middlewares:
            try:
                result = mw.after_tool(tool_name, args, result, ctx)
            except Exception as e:
                logger.warning("Middleware %s.after_tool failed: %s", type(mw).__name__, e)
        return result

    def run_after_agent(self, final_answer: str, ctx: Any) -> str:
        for mw in self._middlewares:
            try:
                final_answer = mw.after_agent(final_answer, ctx)
            except Exception as e:
                logger.warning("Middleware %s.after_agent failed: %s", type(mw).__name__, e)
        return final_answer

    # --- Backward-compatible aliases (used by tool_registry.py) ---

    def run_pre(self, tool_name: str, args: dict, ctx: Any) -> dict:
        return self.run_before_tool(tool_name, args, ctx)

    def run_post(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        return self.run_after_tool(tool_name, args, result, ctx)


# Backward-compatible alias
HookChain = MiddlewareChain


# ============================================================
# Built-in Middlewares
# ============================================================

class AuditHook(ToolHook):
    """Post hook: record every tool call to the tracer (if available on ctx)."""

    def post_tool_use(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        if tool_name == "think":
            return result
        tracer = getattr(ctx, "tracer", None)
        if tracer is not None:
            try:
                is_error = result.startswith("Error:") if result else False
                tracer.record_tool_call(
                    turn=-1,
                    tool_name=tool_name,
                    duration_ms=0,
                    success=not is_error,
                    error_msg=result[:200] if is_error else None,
                )
            except Exception as e:
                logger.debug("AuditHook failed to record: %s", e)
        return result


class SqlReadOnlyHook(ToolHook):
    """Pre hook: block write SQL in query_db tool."""

    _WRITE_PATTERN = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
        re.IGNORECASE,
    )

    def pre_tool_use(self, tool_name: str, args: dict, ctx: Any) -> dict:
        if tool_name != "query_db":
            return args
        query = args.get("query", "") or args.get("sql", "")
        if self._WRITE_PATTERN.search(query):
            raise GuardrailTriggered(
                f"Error: query_db 仅允许 SELECT 查询。检测到写操作关键字，已拦截。"
            )
        return args


class BashGuardrailHook(ToolHook):
    """Pre hook: enhanced shell command safety checks."""

    _DANGEROUS_PATTERNS = [
        re.compile(r"\brm\s+(-[rRf]+\s+)?/", re.IGNORECASE),
        re.compile(r"\bmkfs\b", re.IGNORECASE),
        re.compile(r"\bdd\s+.*of=/dev/", re.IGNORECASE),
        re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),
        re.compile(r"\bchmod\s+777\s+/", re.IGNORECASE),
        re.compile(r"\bcurl\b.*\|\s*(ba)?sh", re.IGNORECASE),
        re.compile(r"\bwget\b.*\|\s*(ba)?sh", re.IGNORECASE),
        re.compile(r":\(\)\{.*:\|:&.*\};:", re.IGNORECASE),
    ]

    def pre_tool_use(self, tool_name: str, args: dict, ctx: Any) -> dict:
        if tool_name != "bash":
            return args

        command = args.get("command", "")
        if not command:
            return args

        for pattern in self._DANGEROUS_PATTERNS:
            if pattern.search(command):
                raise GuardrailTriggered(
                    f"Error: bash 命令包含危险操作，已拦截。请使用更安全的替代方案。"
                )

        workspace = getattr(ctx, "workspace_dir", None)
        if workspace and ".." in command:
            normalized = command.replace("\\", "/")
            if "/../" in normalized or normalized.endswith("/.."):
                raise GuardrailTriggered(
                    f"Error: bash 命令包含路径遍历（..），不允许访问工作目录外的文件。"
                )

        return args


class OutputSanitizationHook(ToolHook):
    """Post hook: redact PII patterns from tool output."""

    _PATTERNS = [
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED_EMAIL]"),
        (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), "[REDACTED_CARD]"),
        (re.compile(r"\b\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b"), None),
    ]

    _EXEMPT_TOOLS = {"query_db", "get_db_schema", "think"}

    def post_tool_use(self, tool_name: str, args: dict, result: str, ctx: Any) -> str:
        if tool_name in self._EXEMPT_TOOLS:
            return result
        if not result or len(result) < 5:
            return result

        for pattern, replacement in self._PATTERNS:
            if replacement is not None:
                result = pattern.sub(replacement, result)
        return result
