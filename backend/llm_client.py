"""
AgentOffice 2D - LLM Client (Gateway Facade)
Mantém compatibilidade com chamadas existentes do workflow_engine e orchestrator,
delegando a execução de inferência e streaming assíncronos ao backend.llm_gateway.
"""

import logging
from typing import AsyncGenerator, Dict, List, Optional

from backend.models import AppConfig
from backend.llm_gateway import (
    BaseLLMAdapter,
    LLMGatewayError,
    LLMGatewayFactory,
)

logger = logging.getLogger("agentoffice.llm_client")


class LLMClientError(LLMGatewayError):
    """Exceção levantada quando a chamada ao modelo de IA falha."""
    pass


class LLMClient:
    """
    Fachada unificada compatível com as versões anteriores.
    Roteia automaticamente chamadas para adaptadores dedicados via LLMGatewayFactory.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.provider = config.provider
        self.base_url = (config.base_url or "").rstrip("/")
        self.model = config.model
        self.api_key = config.api_keys.get(self.provider, "") if hasattr(config, "api_keys") else ""

        # Obtém o adaptador correspondente ao provedor configurado
        self.adapter: BaseLLMAdapter = LLMGatewayFactory.from_config(config)

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        json_mode: bool = False,
        timeout: float = 60.0
    ) -> str:
        """Executa a inferência e retorna a resposta completa em texto."""
        try:
            return await self.adapter.generate(
                messages=messages,
                system_prompt=system_prompt,
                model_override=model_override,
                json_mode=json_mode,
                timeout=timeout
            )
        except LLMGatewayError as e:
            raise LLMClientError(str(e)) from e
        except Exception as e:
            raise LLMClientError(f"Erro na geração de resposta ({self.provider}): {str(e)}") from e

    async def stream_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        timeout: float = 60.0
    ) -> AsyncGenerator[str, None]:
        """Gera resposta em streaming gerando tokens em tempo real."""
        try:
            async for token in self.adapter.stream(
                messages=messages,
                system_prompt=system_prompt,
                model_override=model_override,
                timeout=timeout
            ):
                yield token
        except LLMGatewayError as e:
            raise LLMClientError(str(e)) from e
        except Exception as e:
            raise LLMClientError(f"Erro no streaming ({self.provider}): {str(e)}") from e
