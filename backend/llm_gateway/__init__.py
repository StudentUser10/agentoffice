"""
AgentOffice 2D - LLM Gateway Module
Gateway Universal de LLMs Multi-Provedor para inferência e streaming assíncronos.
"""

from backend.llm_gateway.base_adapter import (
    BaseLLMAdapter,
    LLMGatewayError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMModelNotFoundError,
)
from backend.llm_gateway.ollama_adapter import OllamaAdapter
from backend.llm_gateway.openai_adapter import OpenAIAdapter
from backend.llm_gateway.anthropic_adapter import AnthropicAdapter
from backend.llm_gateway.gemini_adapter import GeminiAdapter
from backend.llm_gateway.factory import LLMGatewayFactory, get_adapter

__all__ = [
    "BaseLLMAdapter",
    "LLMGatewayError",
    "LLMAuthenticationError",
    "LLMConnectionError",
    "LLMTimeoutError",
    "LLMModelNotFoundError",
    "OllamaAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "LLMGatewayFactory",
    "get_adapter",
]
