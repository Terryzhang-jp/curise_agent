"""
Gemini LLM provider — wraps google-genai SDK.

All google.genai imports are confined to this single file.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


# HTTP status codes that are worth retrying on. 4xx codes are caller bugs and
# should fail fast — except 408 (request timeout) and 429 (rate limit), which
# are transient.
_RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable_error(exc: Exception) -> bool:
    """Decide whether a Gemini SDK exception should be retried.

    Conservative: only retry transient infra failures, never logic errors.
    """
    msg = str(exc).lower()

    # Network / SDK-level transient signals
    transient_markers = (
        "timeout", "timed out", "connection reset", "connection aborted",
        "temporarily unavailable", "deadline exceeded",
        "internal error", "service unavailable", "bad gateway",
    )
    if any(marker in msg for marker in transient_markers):
        return True

    # Try to extract numeric HTTP status code from the error message
    for code in _RETRYABLE_HTTP_CODES:
        if str(code) in msg:
            return True

    return False

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
        self._client = genai.Client(
            api_key=config.api_key,
            http_options={"timeout": 180_000},  # 180s timeout to prevent indefinite hangs
        )
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
            max_output_tokens=self._config.max_output_tokens,
        )

    def generate(self, history: list[Any]) -> LLMResponse:
        if self._gen_config is None:
            raise RuntimeError("Provider not configured. Call configure() first.")

        last_error: Exception | None = None
        max_attempts = self._config.max_retries + 1
        for attempt in range(max_attempts):
            try:
                resp = self._client.models.generate_content(
                    model=self._model_name,
                    contents=history,
                    config=self._gen_config,
                )
                return self._parse_response(resp)
            except Exception as e:
                last_error = e
                # Logic errors (4xx other than 408/429) should fail fast.
                if not _is_retryable_error(e):
                    logger.warning(
                        "Gemini generate() non-retryable error on attempt %d/%d: %s",
                        attempt + 1, max_attempts, e,
                    )
                    raise
                if attempt >= max_attempts - 1:
                    logger.error(
                        "Gemini generate() exhausted %d retries, last error: %s",
                        max_attempts, e,
                    )
                    raise
                # Exponential backoff with jitter, capped at 30s
                base_delay = self._config.retry_delay * (2 ** attempt)
                jitter = random.uniform(0, base_delay * 0.25)
                sleep_for = min(base_delay + jitter, 30.0)
                logger.warning(
                    "Gemini generate() retryable error on attempt %d/%d (%s), sleeping %.1fs",
                    attempt + 1, max_attempts, e, sleep_for,
                )
                time.sleep(sleep_for)
        # Unreachable, but mypy/pyright wants it
        assert last_error is not None
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

    def update_tools(self, tools: list) -> None:
        """Update tool declarations mid-session without changing system prompt or thinking config."""
        if self._gen_config is None:
            return
        gemini_tools = self._convert_tools(tools)
        self._gen_config = types.GenerateContentConfig(
            tools=gemini_tools or None,
            system_instruction=self._gen_config.system_instruction,
            thinking_config=self._gen_config.thinking_config,
            max_output_tokens=self._gen_config.max_output_tokens,
        )

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    @staticmethod
    def _build_schema(param_info: dict) -> types.Schema:
        """Recursively build Gemini Schema. Supports string/number/integer/boolean/array/object."""
        type_str = param_info.get("type", "STRING").upper()
        kwargs: dict = {"type": type_str}
        if "description" in param_info:
            kwargs["description"] = param_info["description"]
        if type_str == "ARRAY" and "items" in param_info:
            kwargs["items"] = GeminiProvider._build_schema(param_info["items"])
        if type_str == "OBJECT" and "properties" in param_info:
            props = {}
            for name, info in param_info["properties"].items():
                props[name] = GeminiProvider._build_schema(info)
            kwargs["properties"] = props
            if isinstance(param_info.get("required"), list):
                kwargs["required"] = param_info["required"]
        return types.Schema(**kwargs)

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
                properties[param_name] = GeminiProvider._build_schema(param_info)
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
        thinking_tokens = 0
        if resp.usage_metadata:
            prompt_tokens = resp.usage_metadata.prompt_token_count or 0
            completion_tokens = resp.usage_metadata.candidates_token_count or 0
            thinking_tokens = getattr(resp.usage_metadata, 'thinking_token_count', 0) or 0

        return LLMResponse(
            text_parts=text_parts,
            thinking_parts=thinking_parts,
            function_calls=function_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            thinking_tokens=thinking_tokens,
            raw=content,  # The types.Content for history append
        )
