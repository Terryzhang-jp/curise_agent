"""
DeepSeek LLM provider — OpenAI-compatible API with thinking mode support.

Ported from agent_design/llm/deepseek_provider.py with import paths updated.
"""

from __future__ import annotations

import json
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

_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(LLMProvider):
    """DeepSeek API wrapper.

    Uses the openai SDK with base_url pointed at DeepSeek.
    Supports both standard mode (deepseek-chat) and thinking mode (deepseek-reasoner).
    """

    def __init__(self, config: LLMConfig, base_url: str = _BASE_URL):
        self._config = config
        self._client = OpenAI(api_key=config.api_key, base_url=base_url)
        self._model = config.model_name
        self._thinking = "reasoner" in config.model_name
        self._system_prompt: str = ""
        self._tools: list[dict] | None = None

    # ----------------------------------------------------------
    # LLMProvider interface
    # ----------------------------------------------------------

    def configure(self, system_prompt, tools: list[ToolDeclaration], thinking_budget):
        self._system_prompt = system_prompt
        self._tools = self._convert_tools(tools) if tools else None

    def generate(self, history: list[Any]) -> LLMResponse:
        messages = [{"role": "system", "content": self._system_prompt}] + history

        last_error = None
        for attempt in range(self._config.max_retries + 1):
            try:
                kwargs: dict[str, Any] = dict(
                    model=self._model,
                    messages=messages,
                )
                if self._tools:
                    kwargs["tools"] = self._tools
                    kwargs["tool_choice"] = "auto"

                resp = self._client.chat.completions.create(**kwargs)
                return self._parse_response(resp)
            except Exception as e:
                last_error = e
                if attempt < self._config.max_retries:
                    time.sleep(self._config.retry_delay * (attempt + 1))
                    continue
                raise last_error

    def build_user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def build_tool_results(self, results: list[FunctionResponse]) -> Any:
        msgs = []
        for r in results:
            msg: dict[str, Any] = {
                "role": "tool",
                "content": r.result,
                "tool_call_id": r.id or f"call_{r.name}",
            }
            msgs.append(msg)
        return msgs

    def build_system_injection(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def build_model_message(self, text_parts: list[str], function_calls: list[FunctionCall]) -> Any:
        msg: dict[str, Any] = {"role": "assistant"}
        content = "\n".join(text_parts) if text_parts else None
        if content:
            msg["content"] = content
        if function_calls:
            msg["tool_calls"] = [
                {
                    "id": f"call_{fc.name}",
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(fc.args, ensure_ascii=False),
                    },
                }
                for fc in function_calls
            ]
        return msg

    def build_empty_model_message(self, text: str = "(error recovery)") -> Any:
        return {"role": "assistant", "content": text}

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    @staticmethod
    def _convert_tools(declarations: list[ToolDeclaration]) -> list[dict]:
        """Convert ToolDeclarations to OpenAI/DeepSeek function-calling format."""
        tools = []
        for td in declarations:
            properties = {}
            required = []
            type_map = {
                "STRING": "string",
                "NUMBER": "number",
                "INTEGER": "integer",
                "BOOLEAN": "boolean",
            }
            for param_name, param_info in td.parameters.items():
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

    def _parse_response(self, resp) -> LLMResponse:
        """Parse DeepSeek ChatCompletion into LLMResponse."""
        choice = resp.choices[0]
        message = choice.message

        text_parts = []
        thinking_parts = []
        function_calls = []

        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            thinking_parts.append(reasoning)

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

        raw = self._build_raw_assistant(message)

        return LLMResponse(
            text_parts=text_parts,
            thinking_parts=thinking_parts,
            function_calls=function_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=raw,
        )

    def _build_raw_assistant(self, message) -> dict:
        """Build a dict that can be appended directly to history."""
        msg: dict[str, Any] = {"role": "assistant"}

        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            msg["reasoning_content"] = reasoning

        if message.content:
            msg["content"] = message.content

        if message.tool_calls:
            msg["tool_calls"] = [
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

        return msg
