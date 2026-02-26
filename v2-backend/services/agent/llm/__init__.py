"""LLM provider abstraction layer."""

from services.agent.llm.base import LLMProvider, LLMResponse, FunctionCall, FunctionResponse, ToolDeclaration
from services.agent.llm.gemini_provider import GeminiProvider

# Optional providers — imported lazily via create_provider() or explicit import
# from services.agent.llm.openai_provider import OpenAIProvider
# from services.agent.llm.deepseek_provider import DeepSeekProvider

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "FunctionCall",
    "FunctionResponse",
    "ToolDeclaration",
    "GeminiProvider",
]
