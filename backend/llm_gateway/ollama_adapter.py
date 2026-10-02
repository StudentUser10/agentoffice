"""
AgentOffice 2D - LLM Gateway: Ollama Native Adapter
Adaptador nativo para Ollama com suporte a streaming de tokens e auto-detecção de modelos locais.
"""

import json
import logging
import time
from typing import AsyncGenerator, Dict, List, Optional, Any
import httpx

from backend.llm_gateway.base_adapter import (
    BaseLLMAdapter,
    LLMGatewayError,
    LLMConnectionError,
    LLMTimeoutError,
)

logger = logging.getLogger("agentoffice.llm_gateway.ollama")


class OllamaAdapter(BaseLLMAdapter):
    def __init__(
        self,
        provider: str = "ollama",
        base_url: str = "http://localhost:11434",
        api_key: Optional[str] = None,
        model: Optional[str] = "llama3:latest",
        custom_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        super().__init__(
            provider=provider,
            base_url=base_url or "http://localhost:11434",
            api_key=api_key,
            model=model or "llama3:latest",
            custom_headers=custom_headers,
            **kwargs
        )

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        model: str,
        json_mode: bool = False,
        stream: bool = False
    ) -> Dict[str, Any]:
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "stream": stream
        }
        if json_mode:
            payload["format"] = "json"
        return payload

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        json_mode: bool = False,
        timeout: float = 60.0,
        **kwargs
    ) -> str:
        model = model_override or self.model or "llama3:latest"
        url = f"{self.base_url}/api/chat"
        payload = self._build_payload(messages, system_prompt, model, json_mode=json_mode, stream=False)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(url, json=payload, headers=self.custom_headers)
                if res.status_code != 200:
                    raise LLMGatewayError(f"Ollama respondeu com HTTP {res.status_code}: {res.text[:200]}")
                data = res.json()
                return data.get("message", {}).get("content", "")
        except httpx.ConnectError:
            raise LLMConnectionError(
                f"Não foi possível conectar ao Ollama em '{self.base_url}'. Verifique se 'ollama serve' está ativo."
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError(f"Tempo limite esgotado ({timeout}s) ao chamar Ollama ({model}).")
        except LLMGatewayError:
            raise
        except Exception as e:
            raise LLMGatewayError(f"Falha na comunicação com Ollama: {str(e)}")

    async def stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        timeout: float = 60.0,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        model = model_override or self.model or "llama3:latest"
        url = f"{self.base_url}/api/chat"
        payload = self._build_payload(messages, system_prompt, model, json_mode=False, stream=True)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=self.custom_headers) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        raise LLMGatewayError(f"Ollama streaming HTTP {response.status_code}: {err_text.decode('utf-8', errors='ignore')[:200]}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.ConnectError:
            raise LLMConnectionError(
                f"Não foi possível conectar ao Ollama em '{self.base_url}'. Verifique se o serviço está rodando."
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError(f"Tempo limite esgotado ({timeout}s) no streaming do Ollama.")
        except Exception as e:
            raise LLMGatewayError(f"Erro no streaming do Ollama: {str(e)}")

    async def test_connection(self, timeout: float = 4.0) -> Dict[str, Any]:
        url = f"{self.base_url}/api/tags"
        t0 = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(url, headers=self.custom_headers)
                latency = round((time.perf_counter() - t0) * 1000, 1)

                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                    return {
                        "success": True,
                        "message": f"Conexão com Ollama bem-sucedida! {len(models)} modelo(s) detectado(s).",
                        "models": models,
                        "latency_ms": latency,
                        "details": f"Endpoint: {url}"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Ollama respondeu com status HTTP {res.status_code}.",
                        "models": [],
                        "latency_ms": latency,
                        "details": res.text[:200]
                    }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": "Não foi possível conectar ao Ollama.",
                "models": [],
                "details": f"O serviço não está em execução em '{self.base_url}'. Inicie com 'ollama serve' no terminal."
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "Tempo limite excedido ao conectar ao Ollama.",
                "models": [],
                "details": f"Demorou mais de {timeout}s para responder."
            }
        except Exception as e:
            return {
                "success": False,
                "message": "Falha de conexão com Ollama.",
                "models": [],
                "details": str(e)
            }

    async def list_models(self, timeout: float = 4.0) -> List[str]:
        test_res = await self.test_connection(timeout=timeout)
        return test_res.get("models", [])
