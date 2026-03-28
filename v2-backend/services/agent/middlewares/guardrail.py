"""
Guardrail Provider — DeerFlow-aligned pluggable security policy system.

Replaces hardcoded guardrails with a configurable provider pattern.
Each provider returns allow/deny decisions with reason codes.

Default provider: EnhancedBashGuardrail (extends BashGuardrailHook with
indirect execution detection).
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from services.agent.hooks import Middleware, GuardrailTriggered

logger = logging.getLogger(__name__)


@dataclass
class GuardrailDecision:
    """Result of a guardrail evaluation."""
    allowed: bool
    reason: str = ""
    policy_id: str = ""  # which policy triggered the decision


class GuardrailProvider(ABC):
    """Abstract guardrail provider — implement for custom security policies."""

    @abstractmethod
    def evaluate(self, tool_name: str, args: dict, ctx: Any) -> GuardrailDecision:
        """Evaluate whether a tool call should be allowed."""
        ...


class DefaultGuardrailProvider(GuardrailProvider):
    """Enhanced guardrail with indirect execution detection.

    Extends the original BashGuardrailHook patterns with:
    - Python indirect execution (python -c, eval, exec)
    - Node.js eval patterns
    - Environment variable exfiltration
    - Network exfiltration attempts
    - Privilege escalation
    """

    # Dangerous direct commands (inherited from BashGuardrailHook)
    _DIRECT_PATTERNS = [
        re.compile(r"\brm\s+(-[rRf]+\s+)?/", re.IGNORECASE),
        re.compile(r"\bmkfs\b", re.IGNORECASE),
        re.compile(r"\bdd\s+.*of=/dev/", re.IGNORECASE),
        re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),
        re.compile(r"\bchmod\s+777\s+/", re.IGNORECASE),
        re.compile(r"\bcurl\b.*\|\s*(ba)?sh", re.IGNORECASE),
        re.compile(r"\bwget\b.*\|\s*(ba)?sh", re.IGNORECASE),
        re.compile(r":\(\)\{.*:\|:&.*\};:", re.IGNORECASE),  # fork bomb
    ]

    # NEW: Indirect execution patterns
    _INDIRECT_PATTERNS = [
        # Python code execution
        (re.compile(r"\bpython[23]?\s+(-c|--command)\s", re.IGNORECASE), "python_exec",
         "Python -c 代码执行"),
        # Python dangerous builtins
        (re.compile(r"\b(exec|eval|compile)\s*\(", re.IGNORECASE), "python_eval",
         "Python eval/exec 调用"),
        # Node.js eval
        (re.compile(r"\bnode\s+(-e|--eval)\s", re.IGNORECASE), "node_exec",
         "Node.js -e 代码执行"),
        # Environment variable dump (credential leak risk)
        (re.compile(r"\benv\b|\bprintenv\b|\bset\b.*\bexport", re.IGNORECASE), "env_dump",
         "环境变量导出（可能泄露密钥）"),
        # Network exfiltration
        (re.compile(r"\bcurl\b.*(-d|--data|--upload-file)\b", re.IGNORECASE), "exfil_curl",
         "curl 数据上传"),
        # Privilege escalation
        (re.compile(r"\bsudo\b|\bsu\s+-\b|\bchown\s+root\b", re.IGNORECASE), "priv_esc",
         "权限提升操作"),
        # SSH/SCP (lateral movement)
        (re.compile(r"\bssh\b|\bscp\b", re.IGNORECASE), "lateral_move",
         "SSH/SCP 远程操作"),
    ]

    def evaluate(self, tool_name: str, args: dict, ctx: Any) -> GuardrailDecision:
        if tool_name != "bash":
            return GuardrailDecision(allowed=True)

        command = args.get("command", "")
        if not command:
            return GuardrailDecision(allowed=True)

        # Check direct dangerous patterns
        for pattern in self._DIRECT_PATTERNS:
            if pattern.search(command):
                return GuardrailDecision(
                    allowed=False,
                    reason="命令包含危险操作，已拦截。",
                    policy_id="direct_danger",
                )

        # Check indirect execution patterns
        for pattern, policy_id, reason in self._INDIRECT_PATTERNS:
            if pattern.search(command):
                return GuardrailDecision(
                    allowed=False,
                    reason=f"{reason}，已拦截。请使用更安全的替代方案。",
                    policy_id=policy_id,
                )

        # Check path traversal
        workspace = getattr(ctx, "workspace_dir", None)
        if workspace and ".." in command:
            normalized = command.replace("\\", "/")
            if "/../" in normalized or normalized.endswith("/.."):
                return GuardrailDecision(
                    allowed=False,
                    reason="路径遍历（..），不允许访问工作目录外的文件。",
                    policy_id="path_traversal",
                )

        return GuardrailDecision(allowed=True)


class GuardrailMiddleware(Middleware):
    """Middleware wrapper for GuardrailProvider — pluggable policy enforcement.

    Usage:
        provider = DefaultGuardrailProvider()
        middleware = GuardrailMiddleware(provider)
    """

    def __init__(self, provider: GuardrailProvider | None = None):
        self._provider = provider or DefaultGuardrailProvider()

    def before_tool(self, tool_name: str, args: dict, ctx: Any) -> dict:
        decision = self._provider.evaluate(tool_name, args, ctx)
        if not decision.allowed:
            logger.warning(
                "Guardrail DENIED: tool=%s policy=%s reason=%s",
                tool_name, decision.policy_id, decision.reason,
            )
            raise GuardrailTriggered(f"Error: {decision.reason}")
        return args
