"""
Sub-agent definitions — framework preserved for future activation.

Currently no sub-agents are registered. The framework in sub_agent.py
is preserved for use cases that genuinely require multi-turn agent
delegation with context isolation (e.g., parallel order processing,
deep research across 50+ products).

Activation criteria (enable when ANY of these are true):
  - Single conversations regularly exceed 50 turns
  - Need to process 3+ orders simultaneously
  - Skill-guided single agent consistently fails at multi-step workflows

To activate: register SubAgentConfig entries here, then call
register_all() from main.py and create_delegate_tool() from
create_chat_registry().
"""

_registered = False


def register_all():
    """Register all sub-agent configurations (idempotent).

    No sub-agents registered. See module docstring for activation criteria.
    """
    global _registered
    if _registered:
        return
    _registered = True
