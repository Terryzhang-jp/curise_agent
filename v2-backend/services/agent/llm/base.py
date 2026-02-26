"""
LLM Provider abstraction layer.

Defines the interface that all LLM providers must implement,
plus shared data structures (LLMResponse, FunctionCall, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# Data structures
# ============================================================

@dataclass
class FunctionCall:
    name: str
    args: dict
    id: str | None = None  # Provider-specific call ID (e.g. OpenAI/DeepSeek tool_call_id)


@dataclass
class FunctionResponse:
    name: str
    result: str
    id: str | None = None  # Matching call ID for round-trip


@dataclass
class ToolDeclaration:
    """Provider-agnostic tool declaration."""
    name: str
    description: str
    parameters: dict  # {param_name: {type, description, required?}}


@dataclass
class LLMResponse:
    """Parsed response from an LLM provider."""
    text_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    function_calls: list[FunctionCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: Any = None  # Original provider response for history round-trip


# ============================================================
# Abstract base class
# ============================================================

class LLMProvider(ABC):
    """
    Abstract LLM provider interface.

    Each provider manages its own history format internally.
    The Agent passes opaque history items (list[Any]) — each provider
    knows how to produce and consume its own message types.
    """

    @abstractmethod
    def configure(
        self,
        system_prompt: str,
        tools: list[ToolDeclaration],
        thinking_budget: int,
    ) -> None:
        """Configure the provider with system prompt, tools, and thinking budget."""
        ...

    @abstractmethod
    def generate(self, history: list[Any]) -> LLMResponse:
        """Generate a response given conversation history. May raise on API errors."""
        ...

    @abstractmethod
    def build_user_message(self, text: str) -> Any:
        """Build a user message in the provider's native format."""
        ...

    @abstractmethod
    def build_tool_results(self, results: list[FunctionResponse]) -> Any:
        """Build a tool results message (role=user with function_responses)."""
        ...

    @abstractmethod
    def build_system_injection(self, text: str) -> Any:
        """Build a transient system injection message (e.g. warnings, todo state)."""
        ...
