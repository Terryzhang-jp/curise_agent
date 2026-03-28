"""
ReAct Agent Engine — adapted from agent_design/react_agent.py for v2-backend.

Supports both pipeline use (flat params) and general-purpose use (Config object).
Key features:
- All imports use services.agent.* paths
- HITL (Human-in-the-Loop) support via should_pause
- Slash command expansion via ToolContext skills
- Session management (switch_session, new_session)
- Configurable parallel tool workers
- Context compression (compact)
- 3-tier loop detection (warn → single-warn → force-stop)
- DanglingToolCall auto-repair
- Deferred tool loading with tool_search meta-tool
- 6-hook middleware lifecycle
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Any

from services.agent.config import (
    Config, LLMConfig, AgentConfig, PIPELINE_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT, load_config, load_api_key, create_provider,
)
from services.agent.llm.base import LLMProvider, LLMResponse, FunctionCall, FunctionResponse, ToolDeclaration
from services.agent.storage import (
    Storage, Session, Message,
    text_part, thinking_part, tool_call_part, tool_result_part, finish_part,
)
from services.agent.tool_registry import ToolRegistry
from services.agent.tool_context import ToolContext

logger = logging.getLogger(__name__)

HITL_PAUSE_MARKER = "__HITL_PAUSE__"


def _append_to_history(history: list[Any], item: Any):
    """Append item(s) to history. Handles providers that return a list (e.g. DeepSeek tool results)."""
    if isinstance(item, list):
        history.extend(item)
    else:
        history.append(item)


class ReActAgent:
    """
    ReAct Agent engine.

    Core loop:
    1. User message -> LLM
    2. LLM returns: thinking + text or function_call(tool invocations)
    3. Has tool calls -> execute tools -> check should_pause -> results back to LLM -> step 2
    4. No tool calls -> text is the final answer

    Two construction modes:
    1. Flat params (pipeline/chat): pass provider, storage, registry, ctx, pipeline_session_id directly
    2. Config mode (general): pass config=Config(...) for full agent_design parity
    """

    def __init__(
        self,
        # --- Flat params (existing pipeline/chat callers) ---
        provider: LLMProvider | None = None,
        storage: Storage | None = None,
        registry: ToolRegistry | None = None,
        ctx: ToolContext | None = None,
        pipeline_session_id: str | None = None,
        system_prompt: str = "",
        max_turns: int = 30,
        thinking_budget: int = 4096,
        warn_turns_remaining: int = 3,
        verbose: bool = False,
        on_step: Callable[[dict, int], None] | None = None,
        # --- Config mode (general-purpose, optional) ---
        config: Config | None = None,
    ):
        # Build config if provided
        self.config = config

        self.verbose = verbose
        self.on_step = on_step
        self.step_log: list[dict] = []

        # --- ToolContext ---
        self.ctx = ctx or ToolContext()

        # --- Registry ---
        self.registry = registry or ToolRegistry()

        # --- Storage ---
        self.storage = storage

        # --- Session ID ---
        self.session_id = pipeline_session_id or ""

        # --- Config-derived values ---
        if config is not None:
            self.max_turns = config.agent.max_turns
            self.thinking_budget = config.llm.thinking_budget
            self.warn_turns_remaining = config.agent.warn_turns_remaining
            self.model_name = config.llm.model_name
            self._parallel_workers = config.agent.parallel_tool_workers
            self._loop_window = config.agent.loop_window
            self.loop_threshold = config.agent.loop_threshold
            self._loop_force_stop = config.agent.loop_force_stop
            self._compact_threshold = config.agent.compact_threshold
            self.system_prompt = config.agent.system_prompt or DEFAULT_SYSTEM_PROMPT
        else:
            self.max_turns = max_turns
            self.thinking_budget = thinking_budget
            self.warn_turns_remaining = warn_turns_remaining
            self.model_name = "gemini-3-flash-preview"
            self._parallel_workers = 4
            self._loop_window = 20
            self.loop_threshold = 3
            self._loop_force_stop = 5
            self.system_prompt = system_prompt or PIPELINE_SYSTEM_PROMPT

        # --- Provider ---
        if provider is not None:
            self.provider = provider
        elif config is not None:
            if not config.llm.api_key:
                config.llm.api_key = load_api_key(config.llm.provider)
            self.provider = create_provider(config.llm)
        else:
            raise ValueError("Either provider or config must be provided")

        # --- Skill injection (skip if prompt builder already included skills) ---
        if hasattr(self.ctx, 'skills') and self.ctx.skills:
            skill_summary = self.ctx.get_skill_list_summary()
            if skill_summary and skill_summary not in self.system_prompt:
                self.system_prompt += "\n\n" + skill_summary

        # --- Tracer ---
        self._tracer = self.ctx.tracer if hasattr(self.ctx, 'tracer') else None

        # --- Middleware chain ---
        self._middleware = self.registry.get_hooks()  # MiddlewareChain or None

        # Auto-compact settings (config mode sets this earlier; flat mode uses default)
        if not hasattr(self, '_compact_threshold'):
            self._compact_threshold = 70000
        self._compact_done: bool = False  # Only compact once per run()

        # Auto-inject LoopDetectionMiddleware if not already in middleware chain
        self._ensure_loop_detection_middleware()

        # Register tool_search meta-tool if registry has deferred tools
        self._register_tool_search()

        # Configure provider
        declarations = self.registry.to_declarations()
        self.provider.configure(self.system_prompt, declarations, self.thinking_budget)

    # ----------------------------------------------------------
    # Deferred tool loading: tool_search meta-tool
    # ----------------------------------------------------------

    def _register_tool_search(self):
        """Register the tool_search meta-tool if there are deferred tools."""
        if not self.registry.list_deferred():
            return

        registry = self.registry
        provider = self.provider

        @registry.tool(
            description=(
                "搜索并激活额外的专用工具。当你需要某个功能但当前可用工具中没有时，"
                "用关键词搜索隐藏的专用工具。找到后自动激活，下一轮即可使用。"
            ),
            parameters={
                "query": {
                    "type": "STRING",
                    "description": "搜索关键词，例如 'web'、'product'、'file' 等",
                },
            },
            group="meta",
        )
        def tool_search(query: str = "") -> str:
            if not query:
                deferred = registry.list_deferred()
                if not deferred:
                    return "没有额外的专用工具可供激活。"
                return "可用的专用工具:\n" + "\n".join(
                    f"- {td.name}: {td.description}" for td in deferred
                )

            results = registry.search_deferred(query)
            if not results:
                return f"未找到与 '{query}' 相关的工具。"

            activated = []
            for td in results:
                registry.activate(td.name)
                activated.append(td.name)

            # Update provider's tool declarations
            new_declarations = registry.to_declarations()
            provider.update_tools(new_declarations)

            lines = [f"已激活 {len(activated)} 个工具:"]
            for td in results:
                lines.append(f"- {td.name}: {td.description}")
            lines.append("\n这些工具现在可以直接使用了。")
            return "\n".join(lines)

    # ----------------------------------------------------------
    # Session management
    # ----------------------------------------------------------

    def switch_session(self, session_id: str):
        """Switch to an existing session."""
        if self.storage is None:
            raise RuntimeError("No storage configured")
        session = self.storage.get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        self.session_id = session.id

    def new_session(self, title: str = "New Session"):
        """Create and switch to a new session (requires storage with create_session)."""
        if self.storage is None:
            raise RuntimeError("No storage configured")
        if hasattr(self.storage, 'create_session'):
            session = self.storage.create_session(title)
            self.session_id = session.id
            return session
        raise RuntimeError("Storage does not support create_session")

    # ----------------------------------------------------------
    # History reconstruction: storage Message -> provider messages
    # ----------------------------------------------------------

    def _load_history(self) -> list[Any]:
        """Load history from storage, convert to provider-native format."""
        session = self.storage.get_session(self.session_id)
        after_id = session.summary_message_id if session else None
        messages = self.storage.list_messages(self.session_id, after_id=after_id)

        history: list[Any] = []
        for msg in messages:
            content = self._message_to_provider(msg)
            if content is not None:
                _append_to_history(history, content)

        # Fix any dangling tool calls from prior crashes
        self._fix_dangling_tool_calls(history)

        return history

    def _message_to_provider(self, msg: Message) -> Any:
        """Convert a storage Message to a provider-native message."""
        if msg.role == "user":
            text_contents = []
            fn_responses = []
            for p in msg.parts:
                ptype = p.get("type", "")
                data = p.get("data", {})
                if ptype == "text":
                    text_contents.append(data.get("text", ""))
                elif ptype == "tool_result":
                    fn_responses.append(FunctionResponse(
                        name=data.get("name", "unknown"),
                        result=data.get("result", ""),
                    ))
            if fn_responses:
                return self.provider.build_tool_results(fn_responses)
            if text_contents:
                return self.provider.build_user_message("\n".join(text_contents))
            return None

        elif msg.role == "assistant":
            text_parts_list = []
            function_calls = []
            for p in msg.parts:
                ptype = p.get("type", "")
                data = p.get("data", {})
                if ptype == "text":
                    text_parts_list.append(data.get("text", ""))
                elif ptype == "tool_call":
                    function_calls.append(FunctionCall(
                        name=data.get("name", ""),
                        args=data.get("args", {}),
                    ))
            if text_parts_list or function_calls:
                return self.provider.build_model_message(text_parts_list, function_calls)
            return None

        elif msg.role == "tool":
            fn_responses = []
            for p in msg.parts:
                ptype = p.get("type", "")
                data = p.get("data", {})
                if ptype == "tool_result":
                    fn_responses.append(FunctionResponse(
                        name=data.get("name", "unknown"),
                        result=data.get("result", ""),
                    ))
            if fn_responses:
                return self.provider.build_tool_results(fn_responses)
            return None

        return None

    # ----------------------------------------------------------
    # DanglingToolCall fix
    # ----------------------------------------------------------

    def _fix_dangling_tool_calls(self, history: list[Any]) -> None:
        """Scan history and patch orphaned tool_calls with synthetic error results.

        Gemini requires that every model message with function_calls is followed
        by a user message with matching function_responses. If the engine crashed
        between writing the assistant message and writing tool results, the history
        will have a dangling tool_call. This method detects and patches them.
        """
        if not history:
            return

        i = 0
        while i < len(history):
            item = history[i]

            # Check if this is a model message with function_calls
            func_calls = self._extract_function_calls(item)
            if func_calls:
                # Check if next message has matching function_responses
                next_idx = i + 1
                if next_idx >= len(history) or not self._has_function_responses(history[next_idx]):
                    # Dangling tool call — inject synthetic error responses
                    logger.warning(
                        "DanglingToolCall detected at history[%d]: %s tool_calls without responses. Patching.",
                        i, len(func_calls),
                    )
                    synthetic_responses = [
                        FunctionResponse(
                            name=fc_name,
                            result="Error: 工具执行被中断（上次会话异常退出）。请重新尝试。",
                        )
                        for fc_name in func_calls
                    ]
                    patch = self.provider.build_tool_results(synthetic_responses)
                    # Insert the patch right after the dangling model message
                    if isinstance(patch, list):
                        for j, p in enumerate(patch):
                            history.insert(next_idx + j, p)
                    else:
                        history.insert(next_idx, patch)
            i += 1

    def _extract_function_calls(self, item: Any) -> list[str]:
        """Extract function call names from a history item. Returns empty list if none."""
        # Gemini types.Content
        if hasattr(item, 'role') and hasattr(item, 'parts'):
            if getattr(item, 'role', '') == 'model':
                names = []
                for part in (item.parts or []):
                    if hasattr(part, 'function_call') and part.function_call:
                        names.append(part.function_call.name)
                return names
        return []

    def _has_function_responses(self, item: Any) -> bool:
        """Check if a history item contains function_responses (tool results)."""
        if hasattr(item, 'parts'):
            for part in (item.parts or []):
                if hasattr(part, 'function_response') and part.function_response:
                    return True
        return False

    # ----------------------------------------------------------
    # Logging
    # ----------------------------------------------------------

    def _log(self, step_type: str, content: str, **kwargs):
        step = {
            "type": step_type,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self.step_log.append(step)
        if self.verbose:
            logger.info("[%s] %s", step_type, content[:200])
        if self.on_step:
            self.on_step(step, len(self.step_log))

    # ----------------------------------------------------------
    # Tool execution
    # ----------------------------------------------------------

    def _ensure_loop_detection_middleware(self):
        """Auto-inject LoopDetectionMiddleware if not already in the chain (backward compat)."""
        from services.agent.middlewares.loop_detection import LoopDetectionMiddleware
        if self._middleware:
            # Check if any middleware in the chain is already a LoopDetectionMiddleware
            chain_mws = getattr(self._middleware, '_middlewares', [])
            if not any(isinstance(mw, LoopDetectionMiddleware) for mw in chain_mws):
                self._middleware.add(LoopDetectionMiddleware(
                    window=self._loop_window,
                    warn_threshold=getattr(self, 'loop_threshold', 3),
                    force_stop=self._loop_force_stop,
                ))
        else:
            from services.agent.hooks import MiddlewareChain
            self._middleware = MiddlewareChain([
                LoopDetectionMiddleware(
                    window=self._loop_window,
                    warn_threshold=getattr(self, 'loop_threshold', 3),
                    force_stop=self._loop_force_stop,
                )
            ])

    def _exec_tool(self, name: str, args: dict) -> str:
        return self.registry.execute(name, args)

    # ----------------------------------------------------------
    # Core ReAct loop
    # ----------------------------------------------------------

    def run(self, user_message: str) -> str:
        """Run the ReAct loop, return the final answer.

        Returns:
            - Final answer text if the agent completes naturally
            - "__HITL_PAUSE__<reason>" if a tool triggered should_pause
            - Error message if max turns reached
        """
        self.step_log = []
        self._conversation_parts: list[str] = []  # For MemoryMiddleware extraction

        # Handle /skill-name slash commands
        if hasattr(self.ctx, 'resolve_slash_command') and self.ctx.skills:
            was_skill, user_message = self.ctx.resolve_slash_command(user_message)
            if was_skill:
                self._log("user_input", f"[Skill invoked] {user_message[:200]}...")
            else:
                self._log("user_input", user_message)
        else:
            self._log("user_input", user_message)

        # --- Middleware: before_agent ---
        if self._middleware:
            user_message = self._middleware.run_before_agent(user_message, self.ctx)

        # --- Memory injection: if MemoryMiddleware loaded memories, update system prompt ---
        memory_text = getattr(self.ctx, 'memory_text', '')
        if memory_text and memory_text not in self.system_prompt:
            self.system_prompt = memory_text + "\n\n" + self.system_prompt
            declarations = self.registry.to_declarations()
            self.provider.configure(self.system_prompt, declarations, self.thinking_budget)
            self._log("memory_inject", f"Injected {len(memory_text)} chars of long-term memory")

        # Persist user message
        self.storage.add_user_message(self.session_id, user_message)
        self._conversation_parts.append(f"用户: {user_message[:500]}")

        # Load history for LLM
        history = self._load_history()

        total_prompt_tokens = 0
        total_completion_tokens = 0
        _tool_calls_since_think = 0  # Track tool calls without think for enforcement

        final_answer = None

        for turn in range(self.max_turns):
            # --- Cancel check ---
            if self.ctx.cancel_event and self.ctx.cancel_event.is_set():
                cancel_msg = "操作已被用户取消。"
                self._log("cancelled", cancel_msg)
                self.storage.add_assistant_message(
                    self.session_id,
                    [text_part(cancel_msg), finish_part("cancelled")],
                    model=self.model_name,
                )
                final_answer = cancel_msg
                break

            # --- Midpoint metacognitive checkpoint ---
            midpoint_injection = None
            if turn > 0 and turn == self.max_turns // 2:
                midpoint_injection = self.provider.build_system_injection(
                    f"[System] 中途检查 — 你已使用 {turn}/{self.max_turns} 轮次。"
                    "请用 think 工具评估：(1) 原始目标 (2) 已完成 (3) 是否在正轨 (4) 是否需要调整策略。"
                    "如果任务基本完成，现在就给出最终答案。"
                )
                history.append(midpoint_injection)

            # --- Last turn graceful finish ---
            last_turn_injection = None
            if turn == self.max_turns - 1:
                last_turn_injection = self.provider.build_system_injection(
                    "[System] 这是最后一轮。请总结你已完成的工作和未完成的部分，给出最终答案。"
                )
                history.append(last_turn_injection)

            # --- Dynamic budget warning ---
            remaining = self.max_turns - turn
            if remaining == self.warn_turns_remaining:
                history.append(self.provider.build_system_injection(
                    f"[System] 剩余 {remaining}/{self.max_turns} 轮。"
                    "请尽快总结当前进展并给出最终答案。优先完成最重要的待办任务。"
                ))

            # --- Todo state injection (transient) ---
            todo_injection = None
            todo_state = self.ctx.todo_state_summary()
            if todo_state and turn > 0:
                todo_injection = self.provider.build_system_injection(todo_state)
                history.append(todo_injection)

            # --- Workspace file state injection (transient, DeerFlow pattern) ---
            workspace_injection = None
            ws_summary = getattr(self.ctx, '_workspace_file_summary', '')
            if not ws_summary:
                # Re-scan on each turn (files may have been created mid-conversation)
                ws_dir = getattr(self.ctx, 'workspace_dir', None)
                if ws_dir:
                    from services.agent.middlewares.workspace_state import WorkspaceStateMiddleware
                    files = WorkspaceStateMiddleware._scan_workspace(ws_dir)
                    if files:
                        ws_summary = WorkspaceStateMiddleware._format_file_list(files)
            if ws_summary:
                workspace_injection = self.provider.build_system_injection(ws_summary)
                history.append(workspace_injection)

            # --- Middleware: before_model ---
            if self._middleware:
                history = self._middleware.run_before_model(history, self.ctx)

            # --- DanglingToolCall repair (safety net before every LLM call) ---
            self._fix_dangling_tool_calls(history)

            # Call LLM
            try:
                resp = self.provider.generate(history)
            except Exception as e:
                msg = f"LLM API call failed (turn {turn+1}): {e}"
                self._log("error", msg)
                error_parts = [text_part(msg), finish_part("error")]
                if hasattr(self.storage, 'stream_final_answer'):
                    self.storage.stream_final_answer(
                        self.session_id, error_parts, msg, model=self.model_name
                    )
                else:
                    self.storage.add_assistant_message(
                        self.session_id, error_parts, model=self.model_name
                    )
                final_answer = msg
                break
            finally:
                if todo_injection is not None and todo_injection in history:
                    history.remove(todo_injection)
                if workspace_injection is not None and workspace_injection in history:
                    history.remove(workspace_injection)
                if midpoint_injection is not None and midpoint_injection in history:
                    history.remove(midpoint_injection)
                if last_turn_injection is not None and last_turn_injection in history:
                    history.remove(last_turn_injection)

            # --- Middleware: after_model ---
            if self._middleware:
                resp = self._middleware.run_after_model(resp, self.ctx)

            # Token accounting
            total_prompt_tokens += resp.prompt_tokens
            total_completion_tokens += resp.completion_tokens

            # Tracer: record LLM call
            if self._tracer:
                self._tracer.record_llm_call(
                    turn, self.model_name,
                    resp.prompt_tokens, resp.completion_tokens,
                    getattr(resp, 'thinking_tokens', 0),
                )

            # Handle empty response
            if resp.raw is None and not resp.text_parts and not resp.function_calls:
                self._log("error", f"LLM returned empty response (turn {turn+1}), skipping.")
                history.append(self.provider.build_empty_model_message())
                continue

            # Log thinking parts
            for tp in resp.thinking_parts:
                self._log("thinking", tp)

            # Prepare storage parts
            assistant_storage_parts = []
            for tp in resp.thinking_parts:
                assistant_storage_parts.append(thinking_part(tp))
            for tp in resp.text_parts:
                assistant_storage_parts.append(text_part(tp))
            for fc in resp.function_calls:
                assistant_storage_parts.append(tool_call_part(fc.name, fc.args))

            # Append raw LLM response to history
            if resp.raw is not None:
                history.append(resp.raw)

            # No tool calls -> final answer
            if not resp.function_calls:
                final = "\n".join(resp.text_parts) if resp.text_parts else "(Agent没有产生回复)"
                self._log("final_answer", final)
                self._conversation_parts.append(f"助手: {final[:500]}")

                assistant_storage_parts.append(finish_part("stop"))

                if hasattr(self.storage, 'stream_final_answer'):
                    self.storage.stream_final_answer(
                        self.session_id, assistant_storage_parts, final, model=self.model_name
                    )
                else:
                    self.storage.add_assistant_message(
                        self.session_id, assistant_storage_parts, model=self.model_name
                    )
                if total_prompt_tokens or total_completion_tokens:
                    self.storage.update_token_usage(
                        self.session_id, total_prompt_tokens, total_completion_tokens
                    )
                final_answer = final
                break

            # Has text parts alongside tool calls -> intermediate reasoning
            if resp.text_parts:
                self._log("thinking", "\n".join(resp.text_parts))

            # Persist assistant message (with tool_calls)
            self.storage.add_assistant_message(
                self.session_id, assistant_storage_parts, model=self.model_name
            )

            # --- Tool execution (parallel if multiple) ---
            fn_responses: list[FunctionResponse] = [None] * len(resp.function_calls)  # type: ignore
            tool_storage_parts: list[dict] = [None] * len(resp.function_calls)  # type: ignore

            def _execute_single(idx: int, fc: FunctionCall):
                tool_name = fc.name
                tool_args = fc.args
                fc_id = fc.id
                if tool_name == "think":
                    return idx, tool_name, tool_args, "[Thought recorded]", 0, fc_id
                t0 = time.time()
                result = self._exec_tool(tool_name, tool_args)
                dur = round((time.time() - t0) * 1000)
                return idx, tool_name, tool_args, result, dur, fc_id

            if len(resp.function_calls) == 1:
                idx, tool_name, tool_args, result, dur, fc_id = _execute_single(0, resp.function_calls[0])
                if tool_name == "think":
                    self._log("reflection", tool_args.get("thought", ""))
                else:
                    self._log("tool_call", f"调用 {tool_name}",
                              tool_name=tool_name, tool_args=tool_args)
                    self._log("tool_result", result,
                              tool_name=tool_name, duration_ms=dur)
                    if self._tracer:
                        self._tracer.record_tool_call(
                            turn, tool_name, dur,
                            success=not result.startswith("Error:"),
                            error_msg=result[:200] if result.startswith("Error:") else None,
                        )
                fn_responses[0] = FunctionResponse(name=tool_name, result=result, id=fc_id)
                tool_storage_parts[0] = tool_result_part(tool_name, result, dur)
            else:
                for i, fc in enumerate(resp.function_calls):
                    if fc.name == "think":
                        self._log("reflection", fc.args.get("thought", ""))
                    else:
                        self._log("tool_call", f"调用 {fc.name} (并行 {i+1}/{len(resp.function_calls)})",
                                  tool_name=fc.name, tool_args=fc.args)

                max_workers = min(len(resp.function_calls), self._parallel_workers)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(_execute_single, i, fc): i
                        for i, fc in enumerate(resp.function_calls)
                    }
                    for future in as_completed(futures):
                        idx, tool_name, tool_args, result, dur, fc_id = future.result()
                        if tool_name != "think":
                            self._log("tool_result", result,
                                      tool_name=tool_name, duration_ms=dur)
                            if self._tracer:
                                self._tracer.record_tool_call(
                                    turn, tool_name, dur,
                                    success=not result.startswith("Error:"),
                                    error_msg=result[:200] if result.startswith("Error:") else None,
                                )
                        fn_responses[idx] = FunctionResponse(name=tool_name, result=result, id=fc_id)
                        tool_storage_parts[idx] = tool_result_part(tool_name, result, dur)

            # Persist tool results
            self.storage.create_message(self.session_id, "tool", tool_storage_parts)

            # Track tool calls for memory extraction + think enforcement
            has_think_this_turn = False
            for fr in fn_responses:
                if fr and fr.name == "think":
                    has_think_this_turn = True
                    _tool_calls_since_think = 0
                elif fr and fr.name != "think":
                    result_preview = (fr.result or "")[:200]
                    self._conversation_parts.append(
                        f"工具[{fr.name}]: {result_preview}"
                    )

            if not has_think_this_turn:
                _tool_calls_since_think += len([fr for fr in fn_responses if fr and fr.name != "think"])

            # Append tool results to history
            _append_to_history(history, self.provider.build_tool_results(fn_responses))

            # === Think enforcement: soft reminder after 4+ tool calls without think ===
            if _tool_calls_since_think >= 4:
                history.append(self.provider.build_system_injection(
                    "[System] 你已连续执行 {n} 次工具调用而未进行思考。"
                    "请用 think 工具评估当前进度：目标是否达成？是否在正轨？下一步是什么？"
                    .format(n=_tool_calls_since_think)
                ))
                _tool_calls_since_think = 0  # Reset after reminder

            # === Auto-compact check (supports SummarizationMiddleware flag) ===
            should_compact_mw = getattr(self.ctx, '_should_compact', False)
            if not self._compact_done and (total_prompt_tokens >= self._compact_threshold or should_compact_mw):
                self._log("auto_compact", f"Token count ({total_prompt_tokens}) exceeds threshold ({self._compact_threshold}), compacting...")
                try:
                    self.compact()
                    history = self._load_history()
                    self._compact_done = True
                    self._log("auto_compact", "Context compacted successfully, reloaded history.")
                except Exception as e:
                    self._compact_done = True
                    self._log("error", f"Auto-compact failed: {e}")

            # === Tool Result Clearing (Anthropic pattern) ===
            # Old tool results are no longer needed once the agent processed them.
            # Aggressively clear results older than 6 messages to save context.
            if turn >= 3 and len(history) > 8:
                clear_boundary = max(0, len(history) - 8)
                for hi in range(clear_boundary):
                    item = history[hi]
                    # Gemini format: Content with parts containing function_response
                    if hasattr(item, 'parts'):
                        for part in (item.parts or []):
                            if hasattr(part, 'function_response') and part.function_response:
                                resp_dict = part.function_response.response
                                if isinstance(resp_dict, dict) and 'result' in resp_dict:
                                    val = resp_dict['result']
                                    if isinstance(val, str) and len(val) > 200:
                                        resp_dict['result'] = "[已处理 — 结果已被 agent 使用]"
                    # OpenAI/Kimi format: dict with role=tool
                    elif isinstance(item, dict) and item.get('role') == 'tool':
                        content = item.get('content', '')
                        if isinstance(content, str) and len(content) > 200:
                            item['content'] = "[已处理 — 结果已被 agent 使用]"

            # === HITL pause check (after tool execution) ===
            if self.ctx.should_pause:
                pause_msg = f"[等待用户审核] {self.ctx.pause_reason}"
                self.storage.add_assistant_message(
                    self.session_id,
                    [text_part(pause_msg), finish_part("hitl_pause")],
                    model=self.model_name,
                )
                if total_prompt_tokens or total_completion_tokens:
                    self.storage.update_token_usage(
                        self.session_id, total_prompt_tokens, total_completion_tokens
                    )
                final_answer = f"{HITL_PAUSE_MARKER}{self.ctx.pause_reason}"
                break

            # --- Loop detection: soft warning via middleware ---
            loop_warning = getattr(resp, '_loop_warning', None)
            if loop_warning:
                history.append(self.provider.build_system_injection(
                    f"[System] {loop_warning} "
                    "请用 think 工具分析：(1) 为什么重复调用？(2) 期望不同结果吗？(3) 有哪些替代方法？"
                    "如果没有替代方法，给出最终答案。"
                ))

        # --- Loop exit: either we broke out or exhausted turns ---
        if final_answer is None:
            # Exhausted max_turns
            msg = f"Agent reached max turns ({self.max_turns}) without a final answer."
            self._log("error", msg)
            self.storage.add_assistant_message(
                self.session_id,
                [text_part(msg), finish_part("max_turns")],
                model=self.model_name,
            )
            if total_prompt_tokens or total_completion_tokens:
                self.storage.update_token_usage(
                    self.session_id, total_prompt_tokens, total_completion_tokens
                )
            final_answer = msg

        # --- Build conversation log for MemoryMiddleware extraction ---
        if self._conversation_parts:
            self.ctx._conversation_log = "\n".join(self._conversation_parts)

        # --- Expose step_log to ctx for CompletionVerificationMiddleware ---
        self.ctx._step_log = self.step_log

        # --- Middleware: after_agent ---
        if self._middleware:
            final_answer = self._middleware.run_after_agent(final_answer, self.ctx)

        return final_answer

    # ----------------------------------------------------------
    # Context compression (compact)
    # ----------------------------------------------------------

    def compact(self) -> str:
        """Compress context: generate summary, subsequent chats use summary + new messages."""
        messages = self.storage.list_messages(self.session_id)
        if not messages:
            return "当前 session 没有消息，无需压缩。"

        conversation_text = []
        for msg in messages:
            role_label = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(msg.role, msg.role)
            for p in msg.parts:
                ptype = p.get("type", "")
                data = p.get("data", {})
                if ptype == "text":
                    conversation_text.append(f"{role_label}: {data.get('text', '')}")
                elif ptype == "tool_call":
                    conversation_text.append(
                        f"助手调用工具: {data.get('name', '')}({json.dumps(data.get('args', {}), ensure_ascii=False)})"
                    )
                elif ptype == "tool_result":
                    result_text = data.get("result", "")
                    if len(result_text) > 200:
                        result_text = result_text[:200] + "..."
                    conversation_text.append(f"工具结果[{data.get('name', '')}]: {result_text}")

        full_text = "\n".join(conversation_text)
        if len(full_text) > 12000:
            full_text = full_text[:12000] + "\n... (截断)"

        # Include todo state and workspace info in summary prompt
        extra_context = ""
        todo_state = self.ctx.todo_state_summary()
        if todo_state:
            extra_context += f"\n\n{todo_state}"
        workspace = getattr(self.ctx, 'workspace_dir', None)
        if workspace:
            try:
                import os
                files = os.listdir(workspace)
                if files:
                    extra_context += f"\n\n[工作目录文件]: {', '.join(files[:20])}"
            except OSError:
                pass

        summary_prompt = (
            "请总结以下对话的关键内容，重点包括：\n"
            "1. 已完成的处理步骤和结果\n"
            "2. 当前正在进行什么\n"
            "3. 接下来需要做什么\n"
            "4. 重要的中间结果和数据（如产品数量、匹配率等）\n\n"
            "请用简洁的中文总结：\n\n"
            f"{full_text}{extra_context}"
        )

        try:
            summary_history = [self.provider.build_user_message(summary_prompt)]
            resp = self.provider.generate(summary_history)
            summary_text = "\n".join(resp.text_parts) if resp.text_parts else "(摘要生成失败)"
        except Exception as e:
            return f"摘要生成失败: {e}"

        summary_msg = self.storage.create_message(
            self.session_id,
            "user",
            [text_part(f"[对话摘要] 以下是之前对话的摘要：\n\n{summary_text}")],
        )

        self.storage.update_session(self.session_id, summary_message_id=summary_msg.id)

        return f"Context 压缩完成。摘要已保存。\n\n摘要内容:\n{summary_text}"
