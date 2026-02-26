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
"""

from __future__ import annotations

import hashlib
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
            # Config mode: derive settings from config
            self.max_turns = config.agent.max_turns
            self.thinking_budget = config.llm.thinking_budget
            self.warn_turns_remaining = config.agent.warn_turns_remaining
            self.model_name = config.llm.model_name
            self._parallel_workers = config.agent.parallel_tool_workers
            self._loop_window = config.agent.loop_window
            self.loop_threshold = config.agent.loop_threshold
            self.system_prompt = config.agent.system_prompt or DEFAULT_SYSTEM_PROMPT
        else:
            # Flat param mode: use direct values
            self.max_turns = max_turns
            self.thinking_budget = thinking_budget
            self.warn_turns_remaining = warn_turns_remaining
            self.model_name = "gemini-2.5-flash"
            self._parallel_workers = 4
            self._loop_window = 20
            self.loop_threshold = 3
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

        # --- Skill injection ---
        if hasattr(self.ctx, 'skills') and self.ctx.skills:
            skill_summary = self.ctx.get_skill_list_summary()
            if skill_summary:
                self.system_prompt += "\n\n" + skill_summary

        # Loop detection
        self._recent_calls: deque[str] = deque(maxlen=self._loop_window)

        # Configure provider
        declarations = self.registry.to_declarations()
        self.provider.configure(self.system_prompt, declarations, self.thinking_budget)

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

    def _exec_tool(self, name: str, args: dict) -> str:
        return self.registry.execute(name, args)

    def _call_signature(self, name: str, args: dict) -> str:
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False)
        return f"{name}:{hashlib.md5(args_str.encode()).hexdigest()[:8]}"

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

        # Handle /skill-name slash commands
        if hasattr(self.ctx, 'resolve_slash_command') and self.ctx.skills:
            was_skill, user_message = self.ctx.resolve_slash_command(user_message)
            if was_skill:
                self._log("user_input", f"[Skill invoked] {user_message[:200]}...")
            else:
                self._log("user_input", user_message)
        else:
            self._log("user_input", user_message)

        # Persist user message
        self.storage.add_user_message(self.session_id, user_message)

        # Load history for LLM
        history = self._load_history()

        total_prompt_tokens = 0
        total_completion_tokens = 0

        for turn in range(self.max_turns):
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

            # Call LLM
            try:
                resp = self.provider.generate(history)
            except Exception as e:
                msg = f"LLM API call failed (turn {turn+1}): {e}"
                self._log("error", msg)
                # Write error to storage so frontend receives it via SSE
                error_parts = [text_part(msg), finish_part("error")]
                if hasattr(self.storage, 'stream_final_answer'):
                    self.storage.stream_final_answer(
                        self.session_id, error_parts, msg, model=self.model_name
                    )
                else:
                    self.storage.add_assistant_message(
                        self.session_id, error_parts, model=self.model_name
                    )
                return msg
            finally:
                if todo_injection is not None and todo_injection in history:
                    history.remove(todo_injection)

            # Token accounting
            total_prompt_tokens += resp.prompt_tokens
            total_completion_tokens += resp.completion_tokens

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

                assistant_storage_parts.append(finish_part("stop"))

                # Use streaming path if available (ChatStorage), else fallback
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
                return final

            # Has text parts alongside tool calls -> intermediate reasoning
            if resp.text_parts:
                self._log("thinking", "\n".join(resp.text_parts))

            # Persist assistant message (with tool_calls)
            self.storage.add_assistant_message(
                self.session_id, assistant_storage_parts, model=self.model_name
            )

            # --- Loop detection ---
            loop_detected = False
            for fc in resp.function_calls:
                if fc.name == "think":
                    continue
                sig = self._call_signature(fc.name, fc.args)
                count = sum(1 for s in self._recent_calls if s == sig)
                if count >= self.loop_threshold:
                    loop_detected = True
                self._recent_calls.append(sig)

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
                        fn_responses[idx] = FunctionResponse(name=tool_name, result=result, id=fc_id)
                        tool_storage_parts[idx] = tool_result_part(tool_name, result, dur)

            # Persist tool results
            self.storage.create_message(self.session_id, "tool", tool_storage_parts)

            # Append tool results to history
            _append_to_history(history, self.provider.build_tool_results(fn_responses))

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
                return f"{HITL_PAUSE_MARKER}{self.ctx.pause_reason}"

            # --- Loop detection warning ---
            if loop_detected:
                history.append(self.provider.build_system_injection(
                    "[System] 检测到重复调用相同工具（相同参数）。"
                    "请换一种方法或给出最终答案。"
                ))

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
        return msg

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
        if len(full_text) > 10000:
            full_text = full_text[:10000] + "\n... (截断)"

        summary_prompt = (
            "请总结以下对话的关键内容，重点包括：\n"
            "1. 已完成的处理步骤和结果\n"
            "2. 当前正在进行什么\n"
            "3. 接下来需要做什么\n"
            "4. 重要的中间结果和数据（如产品数量、匹配率等）\n\n"
            "请用简洁的中文总结：\n\n"
            f"{full_text}"
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
