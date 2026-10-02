"""
AgentOffice 2D - LLM Gateway: Anthropic Native Messages Adapter
Implementa suporte nativo para a API Messages da Anthropic (/v1/messages):
- Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus
- Suporte a cabeçalhos x-api-key e anthropic-version
- Separação de blocos de sistema (top-level system parameter)
- Normalização de mensagens multi-turnos (merge de mensagens consecutivas do mesmo papel)
- Streaming via SSE de eventos content_block_delta (text_delta)
- Teste de conexão em 1 clique e listagem de modelos
"""

import json
import logging
import time
from typing import AsyncGenerator, Dict, List, Optional, Any
import httpx

from backend.llm_gateway.base_adapter import (
    BaseLLMAdapter,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMGatewayError,
    LLMModelNotFoundError,
    LLMTimeoutError,
)

logger = logging.getLogger("agentoffice.llm_gateway.anthropic")


class AnthropicAdapter(BaseLLMAdapter):
    DEFAULT_BASE_URL = "https://api.anthropic.com"
    DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
    API_VERSION = "2023-06-01"

    CURATED_MODELS = [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    ]

    def __init__(
        self,
        provider: str = "anthropic",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        resolved_url = (base_url or self.DEFAULT_BASE_URL).strip().rstrip("/")
        super().__init__(
            provider=provider,
            base_url=resolved_url,
            api_key=api_key or "",
            model=model or self.DEFAULT_MODEL,
            custom_headers=custom_headers or {},
            **kwargs
        )

    def _resolve_endpoint(self, path: str) -> str:
        """Normaliza caminho relativo garantindo prefixo /v1 se necessário."""
        clean_base = self.base_url
        if clean_base.endswith("/v1"):
            clean_base = clean_base[:-3]
        return f"{clean_base}/v1/{path.lstrip('/')}"

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        if self.custom_headers:
            headers.update(self.custom_headers)
        return headers

    def _prepare_messages_and_system(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None
    ) -> tuple[Optional[str], List[Dict[str, str]]]:
        """
        Anthropic exige que o prompt de sistema seja passado fora da lista de mensagens
        e que mensagens consecutivas com o mesmo role sejam mescladas.
        Também garante que a conversa comece com uma mensagem de role 'user'.
        """
        system_parts: List[str] = []
        if system_prompt and system_prompt.strip():
            system_parts.append(system_prompt.strip())

        filtered_messages: List[Dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))
            if role == "system":
                if content.strip():
                    system_parts.append(content.strip())
            else:
                filtered_messages.append({"role": role, "content": content})

        # Mesclar mensagens consecutivas com mesmo role (requisito da API Anthropic)
        merged_messages: List[Dict[str, str]] = []
        for msg in filtered_messages:
            if not merged_messages:
                merged_messages.append(dict(msg))
            else:
                last_msg = merged_messages[-1]
                if last_msg["role"] == msg["role"]:
                    last_msg["content"] = f"{last_msg['content']}\n\n{msg['content']}"
                else:
                    merged_messages.append(dict(msg))

        # A primeira mensagem deve ter papel 'user'
        if merged_messages and merged_messages[0]["role"] != "user":
            merged_messages.insert(0, {"role": "user", "content": "Inicie o atendimento."})

        final_system = "\n\n".join(system_parts) if system_parts else None
        return final_system, merged_messages

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        json_mode: bool = False,
        timeout: float = 60.0,
        **kwargs
    ) -> str:
        """Executa chamada não-streaming na API Anthropic Messages."""
        if not self.api_key:
            raise LLMAuthenticationError("Chave de API da Anthropic não informada.")

        endpoint = self._resolve_endpoint("messages")
        model = model_override or self.model or self.DEFAULT_MODEL
        headers = self._get_headers()

        system_text, anthropic_messages = self._prepare_messages_and_system(messages, system_prompt)

        max_tokens = kwargs.get("max_tokens", 4096)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if system_text:
            payload["system"] = system_text

        if json_mode:
            # Anthropic não possui json_object schema nativo unificado como OpenAI,
            # portanto reforçamos via instrução de sistema
            json_instruction = "Responda exclusivamente em formato JSON válido, sem formatações adicionais ou markdown."
            if "system" in payload:
                payload["system"] = f"{payload['system']}\n\n{json_instruction}"
            else:
                payload["system"] = json_instruction

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(endpoint, json=payload, headers=headers)

                if res.status_code == 401 or res.status_code == 403:
                    raise LLMAuthenticationError(
                        f"Falha de autenticação na Anthropic ({res.status_code}): Chave de API inválida."
                    )
                if res.status_code == 404:
                    raise LLMModelNotFoundError(
                        f"Modelo ou endpoint Anthropic não encontrado ({res.status_code}): {res.text}"
                    )
                if res.status_code != 200:
                    raise LLMGatewayError(
                        f"Erro na API Anthropic [{res.status_code}]: {res.text}"
                    )

                data = res.json()
                content_blocks = data.get("content", [])
                text_parts = [
                    block.get("text", "")
                    for block in content_blocks
                    if block.get("type") == "text"
                ]
                return "".join(text_parts)

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Não foi possível conectar ao endpoint Anthropic em {endpoint}. Verifique a rede ou proxy."
            ) from e
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(
                f"Tempo limite excedido ({timeout}s) ao aguardar resposta da Anthropic."
            ) from e
        except LLMGatewayError:
            raise
        except Exception as e:
            raise LLMGatewayError(f"Erro inesperado no adaptador Anthropic: {str(e)}") from e

    async def stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        timeout: float = 60.0,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Gera resposta em streaming via SSE da Anthropic (content_block_delta)."""
        if not self.api_key:
            raise LLMAuthenticationError("Chave de API da Anthropic não informada.")

        endpoint = self._resolve_endpoint("messages")
        model = model_override or self.model or self.DEFAULT_MODEL
        headers = self._get_headers()

        system_text, anthropic_messages = self._prepare_messages_and_system(messages, system_prompt)

        max_tokens = kwargs.get("max_tokens", 4096)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                    if response.status_code == 401 or response.status_code == 403:
                        err_text = await response.aread()
                        raise LLMAuthenticationError(
                            f"Falha de autenticação na Anthropic ({response.status_code}): {err_text.decode('utf-8', errors='ignore')}"
                        )
                    if response.status_code != 200:
                        err_text = await response.aread()
                        raise LLMGatewayError(
                            f"Erro no streaming Anthropic [{response.status_code}]: {err_text.decode('utf-8', errors='ignore')}"
                        )

                    current_event: Optional[str] = None
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            current_event = None
                            continue

                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                            continue

                        if line.startswith("data:"):
                            raw_data = line[5:].strip()
                            if raw_data == "[DONE]":
                                break

                            try:
                                chunk = json.loads(raw_data)
                            except json.JSONDecodeError:
                                continue

                            event_type = chunk.get("type") or current_event

                            # Processa content_block_delta com text_delta
                            if event_type == "content_block_delta":
                                delta = chunk.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    token = delta.get("text", "")
                                    if token:
                                        yield token

                            elif event_type == "error":
                                err_msg = chunk.get("error", {}).get("message", "Erro retornado pela Anthropic.")
                                raise LLMGatewayError(f"Erro no stream Anthropic: {err_msg}")

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Não foi possível conectar ao endpoint Anthropic em {endpoint}."
            ) from e
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(
                f"Tempo limite excedido ({timeout}s) no streaming Anthropic."
            ) from e
        except LLMGatewayError:
            raise
        except Exception as e:
            raise LLMGatewayError(f"Falha no streaming Anthropic: {str(e)}") from e

    async def list_models(self, timeout: float = 5.0) -> List[str]:
        """Tenta consultar endpoint de modelos da Anthropic ou retorna lista curada."""
        if not self.api_key:
            return self.CURATED_MODELS

        endpoint = self._resolve_endpoint("models")
        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(endpoint, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    models = [item.get("id") for item in data.get("data", []) if item.get("id")]
                    if models:
                        return models
        except Exception as e:
            logger.debug("Endpoint /v1/models não disponível na Anthropic (%s), usando lista curada.", str(e))

        return self.CURATED_MODELS

    async def test_connection(self, timeout: float = 6.0) -> Dict[str, Any]:
        """
        Valida a chave da Anthropic e conectividade com a API.
        Tenta listar modelos ou executa uma chamada de inferência mínima de 1 token.
        """
        if not self.api_key:
            return {
                "success": False,
                "message": "Chave de API da Anthropic não fornecida.",
                "models": [],
                "details": "Insira uma chave no formato 'sk-ant-...' para conectar."
            }

        start_time = time.perf_counter()
        headers = self._get_headers()

        # 1. Tentar GET /v1/models primeiro
        models_url = self._resolve_endpoint("models")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(models_url, headers=headers)
                latency = round((time.perf_counter() - start_time) * 1000, 2)

                if res.status_code == 200:
                    data = res.json()
                    models = [item.get("id") for item in data.get("data", []) if item.get("id")]
                    return {
                        "success": True,
                        "message": f"Conexão com Anthropic estabelecida com sucesso! ({latency}ms)",
                        "models": models or self.CURATED_MODELS,
                        "latency_ms": latency,
                        "details": f"API respondeu via /v1/models com {len(models)} modelo(s)."
                    }
                elif res.status_code in (401, 403):
                    return {
                        "success": False,
                        "message": "Falha de autenticação na Anthropic: chave de API inválida.",
                        "models": [],
                        "latency_ms": latency,
                        "details": res.text
                    }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": f"Não foi possível conectar ao host da Anthropic ({self.base_url}).",
                "models": [],
                "details": "Verifique sua conexão com a internet ou configurações de proxy."
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": f"Tempo limite excedido ({timeout}s) ao testar Anthropic.",
                "models": [],
                "details": "O servidor da Anthropic demorou a responder."
            }
        except Exception:
            pass

        # 2. Fallback: mini-chamada de 1 token para validar credenciais
        messages_url = self._resolve_endpoint("messages")
        try:
            start_time = time.perf_counter()
            test_model = self.model or self.DEFAULT_MODEL
            payload = {
                "model": test_model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}]
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(messages_url, json=payload, headers=headers)
                latency = round((time.perf_counter() - start_time) * 1000, 2)

                if res.status_code == 200:
                    return {
                        "success": True,
                        "message": f"Conexão com Anthropic validada com sucesso! ({latency}ms)",
                        "models": self.CURATED_MODELS,
                        "latency_ms": latency,
                        "details": f"Teste de inferência de 1 token aprovado com modelo '{test_model}'."
                    }
                elif res.status_code in (401, 403):
                    return {
                        "success": False,
                        "message": "Falha de autenticação na Anthropic: chave de API inválida.",
                        "models": [],
                        "latency_ms": latency,
                        "details": res.text
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Anthropic retornou código HTTP {res.status_code}.",
                        "models": [],
                        "latency_ms": latency,
                        "details": res.text
                    }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": f"Não foi possível conectar ao host da Anthropic ({self.base_url}).",
                "models": [],
                "details": "Verifique sua conexão com a internet."
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": f"Tempo limite excedido ({timeout}s) na validação de inferência Anthropic.",
                "models": [],
                "details": "O serviço não respondeu no prazo esperado."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Erro inesperado ao testar Anthropic: {str(e)}",
                "models": [],
                "details": str(e)
            }
