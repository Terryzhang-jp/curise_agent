"""
ToolRegistry — tool registration center.

Instance-level, no global state. Supports decorator-based registration,
group queries, and provider-agnostic tool declaration export.
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
    """Tool registry — instance-level, no global state."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._permission_rules: list[dict] = []
        self._permission_callback: Callable[[str, dict], bool] | None = None

    # ----------------------------------------------------------
    # Registration
    # ----------------------------------------------------------

    def tool(
        self,
        description: str,
        parameters: dict,
        group: str = "default",
        examples: list[str] | None = None,
    ):
        """Decorator: register a function as an available tool."""
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
            return fn
        return decorator

    def register(self, tool_def: ToolDef):
        """Directly register a ToolDef."""
        self._tools[tool_def.name] = tool_def

    def remove(self, name: str):
        """Remove a tool by name (no-op if not found)."""
        self._tools.pop(name, None)

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

        Transient errors (ConnectionError, TimeoutError, OSError) are
        automatically retried up to 2 times with exponential backoff.
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

        for attempt in range(3):
            try:
                return str(td.fn(**args))
            except self._TRANSIENT as e:
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
                    continue
                return f"Error: {type(e).__name__}: {e} (已重试 2 次)"
            except Exception as e:
                return f"Error: {type(e).__name__}: {e}"

    # ----------------------------------------------------------
    # Provider-agnostic export
    # ----------------------------------------------------------

    def to_declarations(self, groups: list[str] | None = None) -> list[ToolDeclaration]:
        """Export registered tools as provider-agnostic ToolDeclarations."""
        if groups is not None:
            tools = [t for t in self._tools.values() if t.group in groups]
        else:
            tools = list(self._tools.values())

        return [
            ToolDeclaration(
                name=td.name,
                description=td.description,
                parameters=td.parameters,
            )
            for td in tools
        ]
