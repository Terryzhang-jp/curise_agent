"""
Kimi K2.5 LLM provider — uses OpenAI-compatible API via Moonshot platform.

Kimi K2.5 highlights:
- 93% tool calling accuracy (highest among all models)
- 200-300 tool calls per session
- OpenAI SDK compatible (base_url swap only)
- $0.60/$2.50 per M tokens (1/25 of Claude Opus)

API docs: https://platform.moonshot.ai/docs/guide/kimi-k2-5-quickstart
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

from openai import OpenAI

from services.agent.config import LLMConfig
from services.agent.llm.base import (
    LLMProvider,
    LLMResponse,
    FunctionCall,
    FunctionResponse,
    ToolDeclaration,
)

logger = logging.getLogger(__name__)

# Moonshot has two independent platforms:
#   api.moonshot.cn — China mainland (platform.moonshot.cn keys)
#   api.moonshot.ai — International (platform.moonshot.ai keys)
# Default to .cn; override via MOONSHOT_BASE_URL env var
import os
KIMI_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")


# Same retry classification as gemini_provider — only retry transient infra
# failures, never logic errors (4xx auth/quota are caller bugs).
_RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    transient_markers = (
        "timeout", "timed out", "connection reset", "connection aborted",
        "temporarily unavailable", "deadline exceeded",
        "internal error", "service unavailable", "bad gateway",
    )
    if any(marker in msg for marker in transient_markers):
        return True
    for code in _RETRYABLE_HTTP_CODES:
        if str(code) in msg:
            return True
    return False


class KimiProvider(LLMProvider):
    """Kimi K2.5 provider via OpenAI-compatible Moonshot API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=KIMI_BASE_URL,
            timeout=180.0,  # 180s timeout to prevent indefinite hangs
        )
        self._model = config.model_name or "kimi-k2.5"
        self._system_prompt: str = ""
        self._tools: list[dict] | None = None
        self._thinking_budget = 0

    def configure(self, system_prompt, tools: list[ToolDeclaration], thinking_budget):
        self._system_prompt = system_prompt
        self._tools = self._convert_tools(tools) if tools else None
        self._thinking_budget = thinking_budget

    def generate(self, history: list[Any]) -> LLMResponse:
        messages = [{"role": "system", "content": self._system_prompt}] + history

        last_error: Exception | None = None
        max_attempts = self._config.max_retries + 1
        for attempt in range(max_attempts):
            try:
                kwargs: dict[str, Any] = dict(
                    model=self._model,
                    messages=messages,
                    max_tokens=self._config.max_output_tokens or 16384,
                )
                if self._tools:
                    kwargs["tools"] = self._tools
                    kwargs["tool_choice"] = "auto"

                resp = self._client.chat.completions.create(**kwargs)
                return self._parse_response(resp)
            except Exception as e:
                last_error = e
                # 4xx auth/quota errors should fail fast — retrying a 401 is pointless
                if not _is_retryable_error(e):
                    logger.warning(
                        "Kimi non-retryable error on attempt %d/%d: %s",
                        attempt + 1, max_attempts, e,
                    )
                    raise
                if attempt >= max_attempts - 1:
                    logger.error(
                        "Kimi exhausted %d retries, last error: %s",
                        max_attempts, e,
                    )
                    raise
                base_delay = self._config.retry_delay * (2 ** attempt)
                jitter = random.uniform(0, base_delay * 0.25)
                sleep_for = min(base_delay + jitter, 30.0)
                logger.warning(
                    "Kimi retryable error on attempt %d/%d (%s), sleeping %.1fs",
                    attempt + 1, max_attempts, e, sleep_for,
                )
                time.sleep(sleep_for)
        assert last_error is not None
        raise last_error

    def build_user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def build_tool_results(self, results: list[FunctionResponse]) -> Any:
        """Build tool results in OpenAI tool_call response format."""
        messages = []
        for i, r in enumerate(results):
            msg: dict[str, Any] = {
                "role": "tool",
                "content": r.result,
            }
            if r.id:
                msg["tool_call_id"] = r.id
            else:
                # Use index to guarantee uniqueness (avoid "duplicated" errors)
                msg["tool_call_id"] = f"call_{r.name}_{i}"
            messages.append(msg)
        return messages

    def build_system_injection(self, text: str) -> Any:
        return {"role": "user", "content": f"[System] {text}"}

    def build_model_message(self, text_parts: list[str], function_calls: list[FunctionCall]) -> Any:
        msg: dict[str, Any] = {"role": "assistant"}
        if text_parts:
            msg["content"] = "\n".join(text_parts)
        else:
            msg["content"] = None
        if function_calls:
            msg["tool_calls"] = [
                {
                    "id": fc.id or f"call_{fc.name}_{i}",
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(fc.args, ensure_ascii=False),
                    },
                }
                for i, fc in enumerate(function_calls)
            ]
        return msg

    def build_empty_model_message(self, text: str = "(error recovery)") -> Any:
        return {"role": "assistant", "content": text}

    def update_tools(self, tools: list[ToolDeclaration]) -> None:
        self._tools = self._convert_tools(tools) if tools else None

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    @staticmethod
    def _convert_tools(declarations: list[ToolDeclaration]) -> list[dict]:
        """Convert ToolDeclarations to OpenAI function-calling format."""
        tools = []
        for td in declarations:
            properties = {}
            required = []
            for param_name, param_info in td.parameters.items():
                type_map = {
                    "STRING": "string",
                    "NUMBER": "number",
                    "INTEGER": "integer",
                    "BOOLEAN": "boolean",
                }
                json_type = type_map.get(param_info.get("type", "STRING"), "string")
                properties[param_name] = {
                    "type": json_type,
                    "description": param_info.get("description", ""),
                }
                if param_info.get("required", True):
                    required.append(param_name)

            tools.append({
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return tools

    @staticmethod
    def _parse_response(resp) -> LLMResponse:
        """Parse OpenAI-compatible ChatCompletion into LLMResponse."""
        choice = resp.choices[0]
        message = choice.message

        text_parts = []
        thinking_parts = []
        function_calls = []

        if message.content:
            text_parts.append(message.content)

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                function_calls.append(FunctionCall(
                    name=tc.function.name,
                    args=args,
                    id=tc.id,
                ))

        prompt_tokens = resp.usage.prompt_tokens if resp.usage else 0
        completion_tokens = resp.usage.completion_tokens if resp.usage else 0

        # Build raw message dict for history round-trip.
        # OpenAI-compatible APIs require the assistant message (with tool_calls)
        # to be in history before the tool result messages, otherwise:
        # "tool_call_id is not found" error.
        #
        # Kimi K2.5 with thinking enabled also requires "reasoning_content"
        # in assistant messages, otherwise:
        # "thinking is enabled but reasoning_content is missing" error.
        raw_msg: dict[str, Any] = {"role": "assistant"}
        if message.content:
            raw_msg["content"] = message.content
        else:
            raw_msg["content"] = None  # OpenAI format requires content key

        # Preserve reasoning_content for Kimi thinking mode
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            raw_msg["reasoning_content"] = reasoning
            thinking_parts.append(reasoning)

        if message.tool_calls:
            raw_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        return LLMResponse(
            text_parts=text_parts,
            thinking_parts=thinking_parts,
            function_calls=function_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=raw_msg,
        )
