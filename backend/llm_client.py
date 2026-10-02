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

    def _resolve_model(self, model_override: Optional[str]) -> Optional[str]:
        """
        Sanitiza overrides de modelo por agente.
        Se o provedor atual não for Ollama e o override contiver formato de tag local (ex: 'llama3:latest'),
        faz fallback seguro para o modelo configurado no provedor ativo.
        """
        if not model_override or not model_override.strip():
            return None
        candidate = model_override.strip()
        if self.provider != "ollama" and ":" in candidate:
            logger.warning(
                f"Ignorando model_override '{candidate}' incompatível com o provedor '{self.provider}'. "
                f"Utilizando modelo ativo '{self.model}'."
            )
            return None
        return candidate

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        json_mode: bool = False,
        timeout: float = 60.0
    ) -> str:
        """Executa a inferência e retorna a resposta completa em texto."""
        effective_model = self._resolve_model(model_override)
        try:
            return await self.adapter.generate(
                messages=messages,
                system_prompt=system_prompt,
                model_override=effective_model,
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
        effective_model = self._resolve_model(model_override)
        try:
            async for token in self.adapter.stream(
                messages=messages,
                system_prompt=system_prompt,
                model_override=effective_model,
                timeout=timeout
            ):
                yield token
        except LLMGatewayError as e:
            raise LLMClientError(str(e)) from e
        except Exception as e:
            raise LLMClientError(f"Erro no streaming ({self.provider}): {str(e)}") from e
