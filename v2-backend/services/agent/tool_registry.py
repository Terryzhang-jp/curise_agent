"""
ToolRegistry — tool registration center.

Instance-level, no global state. Supports decorator-based registration,
group queries, provider-agnostic tool declaration export, and deferred
tool loading (tools registered but hidden from LLM until activated).
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from typing import Callable, Any

from services.agent.llm.base import ToolDeclaration


@dataclass
class ToolDef:
    name: str
    fn: Callable
    description: str
    parameters: dict          # {param_name: {type, description, required?}}
    group: str                # "reasoning" | "pipeline" | etc.
    examples: list[str] = field(default_factory=list)


class ToolRegistry:
    """Tool registry — instance-level, no global state.

    Supports deferred tools: registered and executable, but hidden from
    LLM tool declarations until explicitly activated via activate().
    """

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._deferred: set[str] = set()     # Names of deferred (hidden from LLM) tools
        self._permission_rules: list[dict] = []
        self._permission_callback: Callable[[str, dict], bool] | None = None
        self._hooks: Any = None  # MiddlewareChain (optional)
        self._ctx: Any = None    # ToolContext (optional)

    # ----------------------------------------------------------
    # Registration
    # ----------------------------------------------------------

    def tool(
        self,
        description: str,
        parameters: dict,
        group: str = "default",
        examples: list[str] | None = None,
        deferred: bool = False,
    ):
        """Decorator: register a function as an available tool.

        Args:
            deferred: If True, tool is registered but hidden from LLM declarations.
                      It can be discovered via tool_search and activated at runtime.
        """
        def decorator(fn: Callable) -> Callable:
            tool_def = ToolDef(
                name=fn.__name__,
                fn=fn,
                description=description,
                parameters=parameters,
                group=group,
                examples=examples or [],
            )
            self._tools[fn.__name__] = tool_def
            if deferred:
                self._deferred.add(fn.__name__)
            return fn
        return decorator

    def register(self, tool_def: ToolDef, deferred: bool = False):
        """Directly register a ToolDef."""
        self._tools[tool_def.name] = tool_def
        if deferred:
            self._deferred.add(tool_def.name)

    def remove(self, name: str):
        """Remove a tool by name (no-op if not found)."""
        self._tools.pop(name, None)
        self._deferred.discard(name)

    # ----------------------------------------------------------
    # Deferred tool management
    # ----------------------------------------------------------

    def defer(self, name: str):
        """Mark a registered tool as deferred (hidden from LLM)."""
        if name in self._tools:
            self._deferred.add(name)

    def activate(self, name: str) -> bool:
        """Activate a deferred tool (make it visible to LLM).

        Returns True if the tool was deferred and is now active.
        """
        if name in self._deferred:
            self._deferred.discard(name)
            return True
        return False

    def is_deferred(self, name: str) -> bool:
        return name in self._deferred

    def list_deferred(self) -> list[ToolDef]:
        """List all deferred tools (for tool_search results)."""
        return [self._tools[n] for n in self._deferred if n in self._tools]

    def search_deferred(self, query: str) -> list[ToolDef]:
        """Search deferred tools by keyword match on name and description."""
        query_lower = query.lower()
        results = []
        for name in self._deferred:
            td = self._tools.get(name)
            if td and (query_lower in td.name.lower() or query_lower in td.description.lower()):
                results.append(td)
        return results

    # ----------------------------------------------------------
    # Permissions
    # ----------------------------------------------------------

    def set_permissions(self, rules: list[dict]):
        self._permission_rules = rules

    def set_permission_callback(self, callback: Callable[[str, dict], bool]):
        self._permission_callback = callback

    def _check_permission(self, tool_name: str) -> str:
        for rule in self._permission_rules:
            if fnmatch.fnmatch(tool_name, rule.get("tool", "")):
                return rule.get("permission", "allow")
        return "allow"

    def set_hooks(self, hooks):
        """Set the MiddlewareChain for pre/post tool interception."""
        self._hooks = hooks

    def set_ctx(self, ctx):
        """Set the ToolContext for hooks to access."""
        self._ctx = ctx

    def get_hooks(self):
        """Return the MiddlewareChain (or None)."""
        return self._hooks

    # ----------------------------------------------------------
    # Queries
    # ----------------------------------------------------------

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def list_group(self, group: str) -> list[ToolDef]:
        return [t for t in self._tools.values() if t.group == group]

    def groups(self) -> list[str]:
        seen = []
        for t in self._tools.values():
            if t.group not in seen:
                seen.append(t.group)
        return seen

    def names(self) -> list[str]:
        return list(self._tools.keys())

    # ----------------------------------------------------------
    # Execution
    # ----------------------------------------------------------

    _TRANSIENT = (ConnectionError, TimeoutError, OSError)

    def execute(self, name: str, args: dict) -> str:
        """Execute a tool by name, return string result.

        Both active and deferred tools can be executed. Deferred status
        only affects LLM visibility, not executability.
        """
        td = self._tools.get(name)
        if td is None:
            return f"Error: unknown tool '{name}'. Available: {self.names()}"

        permission = self._check_permission(name)
        if permission == "deny":
            return f"Error: tool '{name}' denied by policy"
        if permission == "ask":
            if self._permission_callback:
                if not self._permission_callback(name, args):
                    return f"Error: user denied tool '{name}'"

        # Pre hooks (before_tool)
        if self._hooks:
            from services.agent.hooks import GuardrailTriggered
            try:
                args = self._hooks.run_pre(name, args, self._ctx)
            except GuardrailTriggered as e:
                return e.message

        for attempt in range(3):
            try:
                result = str(td.fn(**args))
                # Post hooks (after_tool)
                if self._hooks:
                    result = self._hooks.run_post(name, args, result, self._ctx)
                return result
            except self._TRANSIENT as e:
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
                    continue
                self._safe_rollback_ctx()
                return f"Error: {type(e).__name__}: {e} (已重试 2 次)"
            except Exception as e:
                # Framework-level DB session protection:
                # If ANY tool throws, rollback the shared session to prevent
                # cascading failures in subsequent tools (DeerFlow: Bulkhead Pattern)
                self._safe_rollback_ctx()
                return f"Error: {type(e).__name__}: {e}"

    def _safe_rollback_ctx(self):
        """Framework-level DB session rollback — prevents cascading failures.

        After rollback, verifies session is healthy with a no-op query.
        Handles Supabase pooler's InFailedSqlTransaction edge case.
        """
        db = getattr(self._ctx, 'db', None) if self._ctx else None
        if db is None:
            return
        try:
            db.rollback()
        except Exception:
            pass
        # Verify session is usable
        try:
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    # ----------------------------------------------------------
    # Provider-agnostic export
    # ----------------------------------------------------------

    def to_declarations(self, groups: list[str] | None = None,
                        include_deferred: bool = False) -> list[ToolDeclaration]:
        """Export registered tools as provider-agnostic ToolDeclarations.

        By default, deferred tools are excluded from declarations
        (they are hidden from the LLM). Set include_deferred=True to
        include all tools.
        """
        if groups is not None:
            tools = [t for t in self._tools.values() if t.group in groups]
        else:
            tools = list(self._tools.values())

        if not include_deferred:
            tools = [t for t in tools if t.name not in self._deferred]

        return [
            ToolDeclaration(
                name=td.name,
                description=td.description,
                parameters=td.parameters,
            )
            for td in tools
        ]
