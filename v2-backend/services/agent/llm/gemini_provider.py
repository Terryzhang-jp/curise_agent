"""
Gemini LLM provider — wraps google-genai SDK.

All google.genai imports are confined to this single file.
"""

from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import types

from services.agent.config import LLMConfig
from services.agent.llm.base import (
    LLMProvider,
    LLMResponse,
    FunctionCall,
    FunctionResponse,
    ToolDeclaration,
)


class GeminiProvider(LLMProvider):
    """Gemini SDK wrapper implementing the LLMProvider interface."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = genai.Client(api_key=config.api_key)
        self._model_name = config.model_name
        self._gen_config: types.GenerateContentConfig | None = None

    # ----------------------------------------------------------
    # LLMProvider interface
    # ----------------------------------------------------------

    def configure(
        self,
        system_prompt: str,
        tools: list[ToolDeclaration],
        thinking_budget: int,
    ) -> None:
        gemini_tools = self._convert_tools(tools)

        # Build ThinkingConfig — thinking_budget may not be supported in all SDK versions
        thinking_kwargs = {"include_thoughts": True}
        try:
            # Try with thinking_budget (newer SDK versions)
            thinking_config = types.ThinkingConfig(thinking_budget=thinking_budget, **thinking_kwargs)
        except Exception:
            # Fallback: include_thoughts only
            thinking_config = types.ThinkingConfig(**thinking_kwargs)

        self._gen_config = types.GenerateContentConfig(
            tools=gemini_tools or None,
            system_instruction=system_prompt,
            thinking_config=thinking_config,
        )

    def generate(self, history: list[Any]) -> LLMResponse:
        if self._gen_config is None:
            raise RuntimeError("Provider not configured. Call configure() first.")

        last_error = None
        for attempt in range(self._config.max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self._model_name,
                    contents=history,
                    config=self._gen_config,
                )
                return self._parse_response(resp)
            except Exception as e:
                last_error = e
                if attempt < self._config.max_retries:
                    time.sleep(self._config.retry_delay * (attempt + 1))
                    continue
                raise last_error

    def build_user_message(self, text: str) -> Any:
        return types.Content(role="user", parts=[types.Part(text=text)])

    def build_tool_results(self, results: list[FunctionResponse]) -> Any:
        parts = [
            types.Part(function_response=types.FunctionResponse(
                name=r.name,
                response={"result": r.result},
            ))
            for r in results
        ]
        return types.Content(role="user", parts=parts)

    def build_system_injection(self, text: str) -> Any:
        return types.Content(role="user", parts=[types.Part(text=text)])

    # ----------------------------------------------------------
    # History reconstruction from storage
    # ----------------------------------------------------------

    def build_model_message(self, text_parts: list[str], function_calls: list[FunctionCall]) -> Any:
        """Build a model message for history reconstruction from storage."""
        parts = []
        for t in text_parts:
            parts.append(types.Part(text=t))
        for fc in function_calls:
            parts.append(types.Part(function_call=types.FunctionCall(
                name=fc.name,
                args=fc.args,
            )))
        if parts:
            return types.Content(role="model", parts=parts)
        return None

    def build_empty_model_message(self, text: str = "(内部错误，重新整理思路继续回答)") -> Any:
        """Build a placeholder model message for error recovery."""
        return types.Content(role="model", parts=[types.Part(text=text)])

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    @staticmethod
    def _convert_tools(declarations: list[ToolDeclaration]) -> list[types.Tool]:
        """Convert provider-agnostic ToolDeclarations to Gemini SDK Tools."""
        if not declarations:
            return []

        fn_declarations = []
        for td in declarations:
            properties = {}
            required = []
            for param_name, param_info in td.parameters.items():
                properties[param_name] = types.Schema(
                    type=param_info.get("type", "STRING"),
                    description=param_info.get("description", ""),
                )
                if param_info.get("required", True):
                    required.append(param_name)

            fn_declarations.append(
                types.FunctionDeclaration(
                    name=td.name,
                    description=td.description,
                    parameters=types.Schema(
                        type="OBJECT",
                        properties=properties,
                        required=required,
                    ),
                )
            )

        return [types.Tool(function_declarations=fn_declarations)]

    @staticmethod
    def _parse_response(resp) -> LLMResponse:
        """Parse a Gemini SDK response into an LLMResponse."""
        candidate = resp.candidates[0] if resp.candidates else None
        content = candidate.content if candidate and candidate.content else None

        text_parts = []
        thinking_parts = []
        function_calls = []

        if content and content.parts:
            for part in content.parts:
                if part.thought and part.text:
                    thinking_parts.append(part.text)
                elif part.text:
                    text_parts.append(part.text)
                if part.function_call:
                    fc_args = dict(part.function_call.args) if part.function_call.args else {}
                    function_calls.append(FunctionCall(
                        name=part.function_call.name,
                        args=fc_args,
                    ))

        prompt_tokens = 0
        completion_tokens = 0
        if resp.usage_metadata:
            prompt_tokens = resp.usage_metadata.prompt_token_count or 0
            completion_tokens = resp.usage_metadata.candidates_token_count or 0

        return LLMResponse(
            text_parts=text_parts,
            thinking_parts=thinking_parts,
            function_calls=function_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=content,  # The types.Content for history append
        )
