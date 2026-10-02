"""
AgentOffice 2D - LLM Gateway: Base Adapter
Contrato unificado e agnóstico para provedores de LLM.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, List, Optional, Any


class LLMGatewayError(Exception):
    """Exceção base do gateway de LLMs."""
    pass


class LLMAuthenticationError(LLMGatewayError):
    """Falha de autenticação (chave inválida ou ausente)."""
    pass


class LLMConnectionError(LLMGatewayError):
    """Falha de rede ou host inacessível."""
    pass


class LLMTimeoutError(LLMGatewayError):
    """Tempo limite de inferência excedido."""
    pass


class LLMModelNotFoundError(LLMGatewayError):
    """Modelo solicitado não encontrado no provedor."""
    pass


class BaseLLMAdapter(ABC):
    """
    Classe base abstrata para todos os adaptadores de provedores de IA.
    Define a interface comum para geração completa, streaming de tokens,
    teste de conexão e listagem de modelos.
    """

    def __init__(
        self,
        provider: str,
        base_url: str,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        self.provider = provider
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.custom_headers = custom_headers or {}
        self.extra_params = kwargs

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        json_mode: bool = False,
        timeout: float = 60.0,
        **kwargs
    ) -> str:
        """Executa a inferência e retorna a resposta textual completa."""
        pass

    @abstractmethod
    async def stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        timeout: float = 60.0,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Gera resposta em streaming contínuo, emitindo tokens parciais."""
        pass

    @abstractmethod
    async def test_connection(self, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Executa verificação de conectividade e autenticação.
        Retorna dicionário com:
        - success: bool
        - message: str
        - models: List[str]
        - latency_ms: Optional[float]
        - details: Optional[str]
        """
        pass

    @abstractmethod
    async def list_models(self, timeout: float = 5.0) -> List[str]:
        """Lista os modelos disponíveis no provedor."""
        pass
