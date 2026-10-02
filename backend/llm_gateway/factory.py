"""
AgentOffice 2D - LLM Gateway: Factory
Instancia e configura o adaptador correto com base no provedor especificado,
nas configurações globais da aplicação (AppConfig) ou em configurações individuais de agentes.
"""

import logging
from typing import Any, Dict, List, Optional, Union

from backend.llm_gateway.base_adapter import BaseLLMAdapter
from backend.llm_gateway.ollama_adapter import OllamaAdapter
from backend.llm_gateway.openai_adapter import OpenAIAdapter
from backend.llm_gateway.anthropic_adapter import AnthropicAdapter
from backend.llm_gateway.gemini_adapter import GeminiAdapter

logger = logging.getLogger("agentoffice.llm_gateway.factory")

# Mapeamento canônico de provedores para classes de adaptadores
ADAPTER_MAP = {
    "ollama": OllamaAdapter,
    "anthropic": AnthropicAdapter,
    "claude": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "google": GeminiAdapter,
    "google_gemini": GeminiAdapter,
    "openai": OpenAIAdapter,
    "groq": OpenAIAdapter,
    "deepseek": OpenAIAdapter,
    "mistral": OpenAIAdapter,
    "together": OpenAIAdapter,
    "fireworks": OpenAIAdapter,
    "perplexity": OpenAIAdapter,
    "openrouter": OpenAIAdapter,
    "openai_compatible": OpenAIAdapter,
    "lmstudio": OpenAIAdapter,
    "vllm": OpenAIAdapter,
    "localai": OpenAIAdapter,
    "koboldcpp": OpenAIAdapter,
    "custom": OpenAIAdapter,
}

# URLs e modelos padrão por provedor
DEFAULT_PROVIDER_METADATA = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "llama3:latest",
        "requires_key": False
    },
    "vllm": {
        "base_url": "http://localhost:8000/v1",
        "model": "default",
        "requires_key": False
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "model": "default",
        "requires_key": False
    },
    "openai_compatible": {
        "base_url": "http://localhost:1234/v1",
        "model": "default",
        "requires_key": False
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "requires_key": True
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-3-5-sonnet-20241022",
        "requires_key": True
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-1.5-flash",
        "requires_key": True
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "requires_key": True
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "requires_key": True
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-large-latest",
        "requires_key": True
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "requires_key": True
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "model": "accounts/fireworks/models/llama-v3p1-70b-instruct",
        "requires_key": True
    },
    "perplexity": {
        "base_url": "https://api.perplexity.ai",
        "model": "sonar-pro",
        "requires_key": True
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "requires_key": True
    },
    "custom": {
        "base_url": "http://localhost:8000/v1",
        "model": "default",
        "requires_key": False
    },
}


class LLMGatewayFactory:
    """Fábrica para instanciar adaptadores unificados de LLMs."""

    @classmethod
    def normalize_provider(cls, provider: str) -> str:
        prov = (provider or "").strip().lower()
        if prov in ("claude",):
            return "anthropic"
        if prov in ("google", "google_gemini"):
            return "gemini"
        return prov or "ollama"

    @classmethod
    def get_adapter(
        cls,
        provider: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> BaseLLMAdapter:
        """
        Instancia o adaptador correto para o provedor informado.
        Se o provedor for desconhecido, utiliza OpenAIAdapter como fallback flexível.
        """
        norm_provider = cls.normalize_provider(provider)
        meta = DEFAULT_PROVIDER_METADATA.get(norm_provider, {})

        resolved_url = base_url or meta.get("base_url")
        resolved_model = model or meta.get("model")

        adapter_cls = ADAPTER_MAP.get(norm_provider, OpenAIAdapter)

        return adapter_cls(
            provider=norm_provider,
            base_url=resolved_url,
            api_key=api_key or "",
            model=resolved_model,
            custom_headers=custom_headers or {},
            **kwargs
        )

    @classmethod
    def from_config(cls, config: Union[Any, Dict[str, Any]]) -> BaseLLMAdapter:
        """
        Instancia um adaptador a partir do AppConfig ou de um dicionário equivalente.
        """
        if hasattr(config, "model_dump"):
            cfg = config.model_dump()
        elif hasattr(config, "dict"):
            cfg = config.dict()
        elif isinstance(config, dict):
            cfg = config
        else:
            cfg = getattr(config, "__dict__", {})

        provider = cfg.get("provider", "ollama")
        norm_provider = cls.normalize_provider(provider)
        base_url = cfg.get("base_url")
        model = cfg.get("model")

        api_keys = cfg.get("api_keys", {})
        # Tenta obter a chave específica do provedor ou fallback genérico
        api_key = api_keys.get(norm_provider, "") or api_keys.get(provider, "") or cfg.get("api_key", "")

        return cls.get_adapter(
            provider=norm_provider,
            base_url=base_url,
            api_key=api_key,
            model=model
        )

    @classmethod
    def from_agent(
        cls,
        agent: Union[Any, Dict[str, Any]],
        fallback_config: Optional[Union[Any, Dict[str, Any]]] = None
    ) -> BaseLLMAdapter:
        """
        Instancia um adaptador personalizado para um agente específico.
        Se o agente possuir sobrescrita de model_name ou provider, aplica essas opções.
        Caso contrário, utiliza a configuração global informada.
        """
        base_adapter = cls.from_config(fallback_config) if fallback_config else cls.get_adapter("ollama")

        agent_dict = agent.model_dump() if hasattr(agent, "model_dump") else (agent.dict() if hasattr(agent, "dict") else dict(agent))
        agent_model = agent_dict.get("model_name", "").strip()
        agent_provider = agent_dict.get("provider", "").strip()

        if not agent_model and not agent_provider:
            return base_adapter

        resolved_provider = agent_provider or base_adapter.provider
        resolved_model = agent_model or base_adapter.model
        resolved_url = base_adapter.base_url
        resolved_key = base_adapter.api_key

        return cls.get_adapter(
            provider=resolved_provider,
            base_url=resolved_url,
            api_key=resolved_key,
            model=resolved_model,
            custom_headers=base_adapter.custom_headers
        )


def get_adapter(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    custom_headers: Optional[Dict[str, str]] = None,
    **kwargs
) -> BaseLLMAdapter:
    """Função utilitária de conveniência para obter um adaptador."""
    return LLMGatewayFactory.get_adapter(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        custom_headers=custom_headers,
        **kwargs
    )
