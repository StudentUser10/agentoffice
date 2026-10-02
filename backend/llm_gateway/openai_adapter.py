"""
AgentOffice 2D - LLM Gateway: OpenAI-Compatible Adapter
Cobre provedores que seguem a especificação OpenAI /v1:
- OpenAI Oficial (GPT-4o, GPT-4o-mini, o1, o3-mini)
- Groq (Llama 3.3, Mixtral)
- DeepSeek API (DeepSeek-V3, DeepSeek-R1 com reasoning_content)
- Mistral AI (Mistral Large, Codestral)
- Together AI, Fireworks AI, Perplexity AI
- OpenRouter (Multi-Model Gateway)
- vLLM, LM Studio, LocalAI, Text-Generation-WebUI, KoboldCPP
- Endpoints Customizados / Corporativos Genéricos
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
    LLMTimeoutError,
)

logger = logging.getLogger("agentoffice.llm_gateway.openai")


class OpenAIAdapter(BaseLLMAdapter):
    DEFAULT_URLS = {
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "deepseek": "https://api.deepseek.com",
        "mistral": "https://api.mistral.ai/v1",
        "together": "https://api.together.xyz/v1",
        "fireworks": "https://api.fireworks.ai/inference/v1",
        "perplexity": "https://api.perplexity.ai",
        "openrouter": "https://openrouter.ai/api/v1",
        "openai_compatible": "http://localhost:1234/v1",
        "lmstudio": "http://localhost:1234/v1",
        "vllm": "http://localhost:8000/v1",
        "custom": "http://localhost:8000/v1"
    }

    def __init__(
        self,
        provider: str = "openai",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        resolved_url = base_url or self.DEFAULT_URLS.get(provider, "https://api.openai.com/v1")
        default_model = "gpt-4o-mini" if provider == "openai" else ("llama-3.3-70b-versatile" if provider == "groq" else "default")
        super().__init__(
            provider=provider,
            base_url=resolved_url,
            api_key=api_key,
            model=model or default_model,
            custom_headers=custom_headers,
            **kwargs
        )

    def _get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Cabeçalhos específicos do OpenRouter
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "http://127.0.0.1:8000"
            headers["X-Title"] = "AgentOffice 2D"

        if self.custom_headers:
            headers.update(self.custom_headers)
        return headers

    def _build_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        model: str
    ) -> List[Dict[str, str]]:
        formatted = []
        is_reasoning_model = model.lower().startswith(("o1", "o3"))

        if system_prompt:
            # Modelos o1/o3 utilizam developer em vez de system
            role = "developer" if is_reasoning_model else "system"
            formatted.append({"role": role, "content": system_prompt})

        for m in messages:
            r = m.get("role", "user")
            c = m.get("content", "")
            if is_reasoning_model and r == "system":
                r = "developer"
            formatted.append({"role": r, "content": c})

        return formatted

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        json_mode: bool = False,
        timeout: float = 60.0,
        **kwargs
    ) -> str:
        model = model_override or self.model or "gpt-4o-mini"
        endpoint = f"{self.base_url}/chat/completions"
        payload_messages = self._build_messages(messages, system_prompt, model)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "stream": False
        }

        # Modelos o1/o3 não aceitam temperature
        if not model.lower().startswith(("o1", "o3")):
            payload["temperature"] = kwargs.get("temperature", 0.7)

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(endpoint, json=payload, headers=headers)

                # Tratamento de fallback para provedores como Groq quando json_mode falha
                if res.status_code == 400 and json_mode and "json_validate_failed" in res.text:
                    logger.warning(
                        f"Provedor '{self.provider}' retornou HTTP 400 (json_validate_failed). "
                        "Retentando automaticamente sem response_format restritivo..."
                    )
                    payload_fallback = dict(payload)
                    payload_fallback.pop("response_format", None)
                    res = await client.post(endpoint, json=payload_fallback, headers=headers)

                # Tratamento de erro Groq tool_use_failed (quando o modelo gera chamada de tool sem tools habilitado no endpoint)
                if res.status_code == 400 and "tool_use_failed" in res.text:
                    try:
                        err_payload = res.json().get("error", {})
                        if failed_gen := err_payload.get("failed_generation"):
                            logger.info(
                                f"Provedor '{self.provider}' retornou HTTP 400 (tool_use_failed). "
                                "Recuperando failed_generation diretamente do corpo do erro."
                            )
                            return str(failed_gen)
                    except Exception:
                        pass

                if res.status_code in (401, 403):
                    raise LLMAuthenticationError(
                        f"Autenticação recusada por '{self.provider}' (HTTP {res.status_code}). Verifique a chave de API configurada."
                    )
                elif res.status_code != 200:
                    raise LLMGatewayError(
                        f"Provedor '{self.provider}' retornou HTTP {res.status_code}: {res.text[:250]}"
                    )

                data = res.json()
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})

                # Tratamento do campo reasoning_content (DeepSeek R1 / Reasoning models)
                content = msg.get("content")
                if not content and "reasoning_content" in msg:
                    content = msg.get("reasoning_content", "")

                return content or ""
        except httpx.ConnectError:
            raise LLMConnectionError(
                f"Não foi possível conectar ao endpoint '{endpoint}'. O servidor está acessível?"
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError(f"Tempo limite ({timeout}s) excedido ao consultar '{self.provider}' ({model}).")
        except (LLMAuthenticationError, LLMConnectionError, LLMTimeoutError, LLMGatewayError):
            raise
        except Exception as e:
            raise LLMGatewayError(f"Erro ao processar chamada com '{self.provider}': {str(e)}")

    async def stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        timeout: float = 60.0,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        model = model_override or self.model or "gpt-4o-mini"
        endpoint = f"{self.base_url}/chat/completions"
        payload_messages = self._build_messages(messages, system_prompt, model)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "stream": True
        }
        if not model.lower().startswith(("o1", "o3")):
            payload["temperature"] = kwargs.get("temperature", 0.7)

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                    if response.status_code in (401, 403):
                        raise LLMAuthenticationError(f"Chave de API inválida no streaming de '{self.provider}'.")
                    elif response.status_code != 200:
                        err_bytes = await response.aread()
                        raise LLMGatewayError(f"Streaming com '{self.provider}' falhou: HTTP {response.status_code}: {err_bytes.decode('utf-8', errors='ignore')[:200]}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    # Tratamento de reasoning_content para DeepSeek R1
                                    if not content and "reasoning_content" in delta and kwargs.get("include_reasoning", False):
                                        content = delta.get("reasoning_content")

                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                continue
        except httpx.ConnectError:
            raise LLMConnectionError(f"Conexão perdida com '{self.provider}' durante streaming.")
        except httpx.TimeoutException:
            raise LLMTimeoutError(f"Tempo limite esgotado ({timeout}s) no streaming de '{self.provider}'.")
        except Exception as e:
            raise LLMGatewayError(f"Erro no streaming com '{self.provider}': {str(e)}")

    async def test_connection(self, timeout: float = 5.0) -> Dict[str, Any]:
        models_url = f"{self.base_url}/models"
        headers = self._get_headers()
        t0 = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(models_url, headers=headers)
                latency = round((time.perf_counter() - t0) * 1000, 1)

                if res.status_code == 200:
                    data = res.json()
                    models = []
                    if "data" in data and isinstance(data["data"], list):
                        models = [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]
                    elif isinstance(data, list):
                        models = [m.get("id") or m.get("name") for m in data if isinstance(m, dict)]

                    return {
                        "success": True,
                        "message": f"Conexão com '{self.provider}' validada! {len(models)} modelo(s) detectado(s).",
                        "models": models[:30],
                        "latency_ms": latency,
                        "details": f"Endpoint: {models_url}"
                    }
                elif res.status_code in (401, 403):
                    return {
                        "success": False,
                        "message": f"Falha de autenticação no provedor '{self.provider}'.",
                        "models": [],
                        "latency_ms": latency,
                        "details": f"Status HTTP {res.status_code}: Chave de API inválida, expirada ou sem permissões."
                    }
                else:
                    # Alguns servidores (ex: proxies simples) não têm endpoint /models.
                    # Tenta fallback com uma inferência mínima de 1 token.
                    return await self._fallback_ping_test(client, timeout, headers)

        except httpx.ConnectError:
            return {
                "success": False,
                "message": f"Não foi possível conectar ao provedor '{self.provider}'.",
                "models": [],
                "details": f"Falha de rede em '{self.base_url}'. Verifique a URL e a conexão com a internet."
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": f"Tempo limite excedido ({timeout}s) ao testar '{self.provider}'.",
                "models": [],
                "details": "O servidor demorou muito para responder."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Erro de conexão com '{self.provider}'.",
                "models": [],
                "details": str(e)
            }

    async def _fallback_ping_test(
        self,
        client: httpx.AsyncClient,
        timeout: float,
        headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Testa conexão enviando 1 token mínimo quando /models não existir."""
        endpoint = f"{self.base_url}/chat/completions"
        t0 = time.perf_counter()
        payload = {
            "model": self.model or "default",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1
        }
        try:
            res = await client.post(endpoint, json=payload, headers=headers)
            latency = round((time.perf_counter() - t0) * 1000, 1)

            if res.status_code == 200:
                return {
                    "success": True,
                    "message": f"Conexão com '{self.provider}' confirmada via inferência de teste!",
                    "models": [self.model] if self.model else [],
                    "latency_ms": latency,
                    "details": "Validado via /chat/completions"
                }
            elif res.status_code in (401, 403):
                return {
                    "success": False,
                    "message": f"Chave de API inválida para '{self.provider}'.",
                    "models": [],
                    "latency_ms": latency,
                    "details": f"HTTP {res.status_code}"
                }
            else:
                return {
                    "success": False,
                    "message": f"Servidor retornou HTTP {res.status_code}.",
                    "models": [],
                    "latency_ms": latency,
                    "details": res.text[:200]
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Falha no teste com '{self.provider}'.",
                "models": [],
                "details": str(e)
            }

    async def list_models(self, timeout: float = 5.0) -> List[str]:
        test_res = await self.test_connection(timeout=timeout)
        return test_res.get("models", [])
