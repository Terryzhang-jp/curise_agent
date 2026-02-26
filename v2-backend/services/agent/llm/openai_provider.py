"""
OpenAI LLM provider — wraps the OpenAI Python SDK.

Ported from agent_design/llm/openai_provider.py with import paths updated.
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


class OpenAIProvider(LLMProvider):
    """OpenAI SDK wrapper implementing the LLMProvider interface."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = OpenAI(api_key=config.api_key)
        self._model = config.model_name
        self._system_prompt: str = ""
        self._tools: list[dict] | None = None

    # ----------------------------------------------------------
    # LLMProvider interface
    # ----------------------------------------------------------

    def configure(self, system_prompt, tools: list[ToolDeclaration], thinking_budget):
        self._system_prompt = system_prompt
        self._tools = self._convert_tools(tools) if tools else None

    def generate(self, history: list[Any]) -> LLMResponse:
        # Prepend system message
        messages = [{"role": "system", "content": self._system_prompt}] + history

        last_error = None
        for attempt in range(self._config.max_retries + 1):
            try:
                kwargs = dict(model=self._model, messages=messages)
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
        parts = [f"[{r.name}]: {r.result}" for r in results]
        return {"role": "user", "content": "\n\n".join(parts)}

    def build_system_injection(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def build_model_message(self, text_parts: list[str], function_calls: list[FunctionCall]) -> Any:
        content = "\n".join(text_parts) if text_parts else None
        msg: dict[str, Any] = {"role": "assistant"}
        if content:
            msg["content"] = content
        return msg

    def build_empty_model_message(self, text: str = "(error recovery)") -> Any:
        return {"role": "assistant", "content": text}

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
        """Parse OpenAI ChatCompletion into LLMResponse."""
        choice = resp.choices[0]
        message = choice.message

        text_parts = []
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
                ))

        prompt_tokens = resp.usage.prompt_tokens if resp.usage else 0
        completion_tokens = resp.usage.completion_tokens if resp.usage else 0

        return LLMResponse(
            text_parts=text_parts,
            thinking_parts=[],
            function_calls=function_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=None,
        )
