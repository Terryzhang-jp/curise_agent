"""
Sub-agent definitions — register all available sub-agents.

Import this module to populate SUB_AGENT_REGISTRY.

Note: excel_generator sub-agent was removed in favor of direct
generate_inquiries tool (DeerFlow pattern: direct tool calls for
deterministic operations).
"""

_registered = False


def register_all():
    """Register all sub-agent configurations (idempotent).

    Currently no sub-agents are registered. The framework in sub_agent.py
    is preserved for future use cases that genuinely require multi-turn
    agent delegation (e.g., open-ended research tasks).
    """
    global _registered
    if _registered:
        return
    _registered = True
