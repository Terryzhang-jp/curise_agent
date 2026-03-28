"""
Prompt builder — assembles system prompts from composable layers.

Usage:
    ctx = PromptContext(enabled_tools={"query_db", "bash"}, skill_summary="...")
    prompt = build_chat_prompt(ctx)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.agent.prompts.layers import (
    identity,
    capabilities,
    domain_knowledge,
    constraints,
)


@dataclass
class PromptContext:
    """All inputs needed to assemble a system prompt."""
    enabled_tools: set[str] | None = None
    skill_summary: str = ""
    scenario: str | None = None
    registered_tool_names: set[str] | None = None
    memory_text: str = ""  # DeerFlow: injected long-term memory


def build_chat_prompt(ctx: PromptContext) -> str:
    """Assemble a chat system prompt from layers.

    Layer order (DeerFlow aligned):
      1. Identity — who the agent is
      2. Memory — long-term user knowledge (DeerFlow <memory> tag)
      3. Capabilities — tools and skills available
      4. Domain knowledge — business rules, schemas, workflows
      5. Constraints — metacognition, safety
    """
    layers = [
        identity(ctx),
        _memory_layer(ctx),
        capabilities(ctx),
        domain_knowledge(ctx),
        constraints(ctx),
    ]

    # Filter empty layers and join with double newline
    return "\n\n".join(layer for layer in layers if layer)


def _memory_layer(ctx: PromptContext) -> str:
    """DeerFlow <memory> layer — inject long-term user knowledge."""
    if not ctx.memory_text:
        return ""
    return ctx.memory_text
