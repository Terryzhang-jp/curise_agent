"""
Sub-Agent Framework — delegate specialized tasks to isolated child agents.

Pattern inspired by Claude Code's Agent tool + DeerFlow's SubagentExecutor:
- Parent agent calls `delegate` tool with (sub_agent_name, prompt)
- Framework spawns independent ReActAgent with own context/storage/tools
- Sub-agent runs to completion, returns final text as tool result
- Parent's context is protected from sub-agent's intermediate steps

DeerFlow 2.0 alignment:
- Timeout mechanism (configurable per sub-agent)
- Recursive delegation protection (_is_sub_agent flag)
- DB task tracking (v2_sub_agent_tasks)
- Concurrent execution via ThreadPoolExecutor
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable

from services.agent.config import LLMConfig, load_api_key, create_provider
from services.agent.engine import ReActAgent
from services.agent.memory_storage import MemoryStorage
from services.agent.tool_context import ToolContext
from services.agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


# ============================================================
# Sub-Agent Configuration
# ============================================================

@dataclass
class SubAgentConfig:
    """Defines a sub-agent type that can be delegated to."""

    name: str
    description: str  # Shown to parent agent for tool selection
    model_name: str = "gemini-2.5-flash"
    system_prompt: str = ""
    enabled_tools: set[str] = field(default_factory=set)
    max_turns: int = 15
    thinking_budget: int = 2048
    timeout_seconds: int = 120  # DeerFlow: configurable timeout
    # Factory function to register extra tools: (registry, ctx) -> None
    extra_tool_setup: Callable[[ToolRegistry, ToolContext], None] | None = None


# ============================================================
# Registry of available sub-agents
# ============================================================

SUB_AGENT_REGISTRY: dict[str, SubAgentConfig] = {}


def register_sub_agent(config: SubAgentConfig):
    """Register a sub-agent configuration."""
    SUB_AGENT_REGISTRY[config.name] = config
    logger.info("Registered sub-agent: %s (model=%s, timeout=%ds)",
                config.name, config.model_name, config.timeout_seconds)


def get_sub_agent_list() -> str:
    """Return formatted list of available sub-agents for system prompt injection."""
    if not SUB_AGENT_REGISTRY:
        return ""
    lines = ["## 可委派的子Agent"]
    for cfg in SUB_AGENT_REGISTRY.values():
        lines.append(f"- **{cfg.name}**: {cfg.description}")
    lines.append("")
    lines.append("使用 `delegate` 工具将任务委派给专门的子Agent。")
    return "\n".join(lines)


# ============================================================
# DB Task Tracking
# ============================================================

def _record_task_start(db, session_id: str, turn: int | None, name: str, description: str) -> int | None:
    """Record sub-agent task start in v2_sub_agent_tasks. Returns task row id."""
    if not db:
        return None
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            INSERT INTO v2_sub_agent_tasks (parent_session_id, parent_turn, sub_agent_name, task_description, status)
            VALUES (:sid, :turn, :name, :desc, 'running')
            RETURNING id
        """), {"sid": session_id, "turn": turn, "name": name, "desc": description[:2000]})
        row = result.fetchone()
        db.commit()
        return row[0] if row else None
    except Exception as e:
        logger.debug("Failed to record sub-agent task start: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _record_task_end(db, task_id: int | None, status: str, result_preview: str = "",
                     error_msg: str = "", duration_ms: int = 0):
    """Update sub-agent task completion in DB."""
    if not db or not task_id:
        return
    try:
        from sqlalchemy import text
        db.execute(text("""
            UPDATE v2_sub_agent_tasks
            SET status = :status,
                result_preview = :preview,
                error_message = :error,
                duration_ms = :dur,
                completed_at = NOW()
            WHERE id = :tid
        """), {
            "status": status,
            "preview": (result_preview or "")[:500],
            "error": (error_msg or "")[:2000],
            "dur": duration_ms,
            "tid": task_id,
        })
        db.commit()
    except Exception as e:
        logger.debug("Failed to record sub-agent task end: %s", e)
        try:
            db.rollback()
        except Exception:
            pass


# ============================================================
# Sub-Agent Execution
# ============================================================

def run_sub_agent(
    name: str,
    prompt: str,
    parent_ctx: ToolContext,
    chat_storage: Any | None = None,
    session_id: str | None = None,
) -> str:
    """Spawn and run a sub-agent to completion with timeout protection.

    Args:
        name: Sub-agent name (must exist in SUB_AGENT_REGISTRY).
        prompt: The task description — sole data channel to sub-agent.
        parent_ctx: Parent's ToolContext (used to inherit workspace_dir and db).
        chat_storage: Optional ChatStorage for SSE display message push.
        session_id: Parent's session ID (for SSE routing + DB tracking).

    Returns:
        Sub-agent's final text answer.

    Raises:
        ValueError: If sub-agent name is not registered.
        RuntimeError: If sub-agent fails or times out.
    """
    config = SUB_AGENT_REGISTRY.get(name)
    if config is None:
        available = ", ".join(SUB_AGENT_REGISTRY.keys()) or "(none)"
        raise ValueError(f"Unknown sub-agent: {name}. Available: {available}")

    start_time = time.time()
    logger.info("[SubAgent:%s] Starting — prompt=%s...", name, prompt[:100])

    # DB task tracking
    task_id = _record_task_start(
        parent_ctx.db, session_id or "", None, name, prompt
    )

    # 1. Create isolated ToolContext (inherits workspace + db only)
    #    Mark as sub-agent to prevent recursive delegation
    child_ctx = ToolContext(
        workspace_dir=parent_ctx.workspace_dir,
        db=parent_ctx.db,
        skill_paths=parent_ctx.skill_paths,
    )
    child_ctx._is_sub_agent = True  # DeerFlow: recursive protection flag
    # Scan skills so sub-agent can use_skill if needed
    child_ctx.scan_skills()

    # 2. Create isolated ToolRegistry with sub-agent's tool set
    #    NOTE: delegate tool is NOT registered for sub-agents (recursive protection)
    from services.tools import create_chat_registry
    child_registry = create_chat_registry(child_ctx, config.enabled_tools or None)

    # Run extra tool setup if provided
    if config.extra_tool_setup:
        config.extra_tool_setup(child_registry, child_ctx)

    # 3. Create isolated MemoryStorage (no DB writes for sub-agent history)
    child_storage = MemoryStorage(session_id=f"sub-{name}-{int(time.time())}")

    # 4. Create LLM provider with sub-agent's model
    llm_config = LLMConfig(
        model_name=config.model_name,
        api_key=load_api_key("gemini"),
        thinking_budget=config.thinking_budget,
    )
    child_provider = create_provider(llm_config)

    # 5. Push start event via SSE if chat_storage available
    if chat_storage and session_id:
        _push_sub_agent_event(chat_storage, session_id, name, "start", {
            "model": config.model_name,
            "prompt_preview": prompt[:200],
            "timeout_seconds": config.timeout_seconds,
        })

    # 6. Build and run ReActAgent with timeout protection
    def _run():
        agent = ReActAgent(
            provider=child_provider,
            storage=child_storage,
            registry=child_registry,
            ctx=child_ctx,
            system_prompt=config.system_prompt,
            max_turns=config.max_turns,
            thinking_budget=config.thinking_budget,
        )
        return agent.run(prompt)

    try:
        # DeerFlow pattern: ThreadPoolExecutor with timeout
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            try:
                result = future.result(timeout=config.timeout_seconds)
            except FuturesTimeoutError:
                elapsed_ms = round((time.time() - start_time) * 1000)
                logger.error("[SubAgent:%s] Timed out after %ds", name, config.timeout_seconds)
                _record_task_end(parent_ctx.db, task_id, "timeout",
                                 duration_ms=elapsed_ms)
                if chat_storage and session_id:
                    _push_sub_agent_event(chat_storage, session_id, name, "timeout", {
                        "timeout_seconds": config.timeout_seconds,
                    })
                raise RuntimeError(
                    f"Sub-agent '{name}' timed out after {config.timeout_seconds}s. "
                    "Task may be too complex — consider breaking it into smaller steps."
                )

    except RuntimeError:
        raise  # re-raise timeout
    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000)
        logger.error("[SubAgent:%s] Failed after %.1fs: %s", name, elapsed_ms / 1000, e)
        _record_task_end(parent_ctx.db, task_id, "failed",
                         error_msg=str(e), duration_ms=elapsed_ms)
        if chat_storage and session_id:
            _push_sub_agent_event(chat_storage, session_id, name, "error", {
                "error": str(e),
                "elapsed_seconds": round(elapsed_ms / 1000, 1),
            })
        raise RuntimeError(f"Sub-agent '{name}' failed: {e}") from e

    elapsed_ms = round((time.time() - start_time) * 1000)
    logger.info("[SubAgent:%s] Completed in %.1fs — result=%s...",
                name, elapsed_ms / 1000, result[:100])

    # Record success
    _record_task_end(parent_ctx.db, task_id, "completed",
                     result_preview=result, duration_ms=elapsed_ms)

    # Push completion event
    if chat_storage and session_id:
        _push_sub_agent_event(chat_storage, session_id, name, "done", {
            "elapsed_seconds": round(elapsed_ms / 1000, 1),
            "result_preview": result[:200],
        })

    return result


# ============================================================
# SSE Helper
# ============================================================

def _push_sub_agent_event(
    chat_storage: Any,
    session_id: str,
    agent_name: str,
    event_type: str,
    data: dict,
):
    """Push a sub-agent lifecycle event via SSE queue."""
    try:
        from services.agent.stream_queue import push_event
        push_event(session_id, {
            "type": f"sub_agent_{event_type}",
            "data": {
                "agent_name": agent_name,
                **data,
            },
        })
    except Exception as e:
        logger.warning("Failed to push sub-agent SSE event: %s", e)


# ============================================================
# Delegate Tool Factory
# ============================================================

def create_delegate_tool(registry: ToolRegistry, ctx: ToolContext,
                         chat_storage: Any = None, session_id: str | None = None):
    """Register the `delegate` tool on the parent agent's registry.

    This is the parent-side tool that triggers sub-agent execution.
    NOTE: This tool is NOT registered for sub-agents (recursive protection).
    """
    # Skip if this is a sub-agent context
    if getattr(ctx, '_is_sub_agent', False):
        logger.debug("Skipping delegate tool registration for sub-agent context")
        return

    # Build description dynamically from registered sub-agents
    agent_list = "\n".join(
        f"  - {cfg.name}: {cfg.description}"
        for cfg in SUB_AGENT_REGISTRY.values()
    )
    tool_desc = (
        f"将任务委派给专门的子Agent执行。子Agent有独立的上下文和工具，"
        f"��行完成后返回结果文本。\n可用子Agent:\n{agent_list}"
    )

    @registry.tool(
        description=tool_desc,
        parameters={
            "agent_name": {
                "type": "STRING",
                "description": "��Agent名称",
            },
            "task": {
                "type": "STRING",
                "description": "任务描述（越详细越好，这是传给子Agent的唯一信息）",
            },
        },
    )
    def delegate(agent_name: str, task: str) -> str:
        try:
            result = run_sub_agent(
                name=agent_name,
                prompt=task,
                parent_ctx=ctx,
                chat_storage=chat_storage,
                session_id=session_id,
            )
            return result
        except (ValueError, RuntimeError) as e:
            return f"Error: {e}"
