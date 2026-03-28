"""
Prompt layered assembly system.

Builds system prompts from composable layers:
  1. Identity — who the agent is
  2. Capabilities — what it can do (tools, skills)
  3. Domain knowledge — business rules, data schemas, workflows
  4. Constraints — metacognition, safety rules
  5. State — session context, active tasks

Usage:
    from services.agent.prompts import build_chat_prompt, PromptContext

    ctx = PromptContext(enabled_tools={"query_db", "bash"}, ...)
    prompt = build_chat_prompt(ctx)
"""

from services.agent.prompts.builder import build_chat_prompt, PromptContext

__all__ = ["build_chat_prompt", "PromptContext"]
