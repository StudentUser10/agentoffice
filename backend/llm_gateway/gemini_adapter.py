"""
AgentOffice 2D - LLM Gateway: Google Gemini Native Adapter
Implementa suporte nativo para a API Google Generative Language:
- Gemini 1.5 Pro, Gemini 1.5 Flash, Gemini 2.0 Flash
- Suporte a geração completa (generateContent) e streaming contínuo SSE (streamGenerateContent?alt=sse)
- Suporte a system_instruction nativo e responseMimeType (JSON mode)
- Teste de conexão em 1 clique e listagem dinâmica de modelos via /v1beta/models
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

logger = logging.getLogger("agentoffice.llm_gateway.gemini")


class GeminiAdapter(BaseLLMAdapter):
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
    DEFAULT_MODEL = "gemini-1.5-flash"

    CURATED_MODELS = [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-exp",
        "gemini-1.0-pro",
    ]

    def __init__(
        self,
        provider: str = "gemini",
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

    def _clean_model_name(self, model: str) -> str:
        """Garante que o nome do modelo não possua prefixo duplicado 'models/'."""
        m = (model or self.model or self.DEFAULT_MODEL).strip()
        if m.startswith("models/"):
            m = m[7:]
        return m

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key
        if self.custom_headers:
            headers.update(self.custom_headers)
        return headers

    def _build_contents_and_system(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None
    ) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Estrutura mensagens para o formato do Gemini:
        role 'user' e role 'model'.
        System prompt é separado no objeto 'system_instruction'.
        """
        system_parts: List[str] = []
        if system_prompt and system_prompt.strip():
            system_parts.append(system_prompt.strip())

        gemini_contents: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))

            if role == "system":
                if content.strip():
                    system_parts.append(content.strip())
            else:
                gemini_role = "user" if role in ("user", "human") else "model"
                gemini_contents.append({
                    "role": gemini_role,
                    "parts": [{"text": content}]
                })

        system_instruction = None
        if system_parts:
            system_instruction = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }

        return system_instruction, gemini_contents

    def _build_payload(
        self,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[Dict[str, Any]],
        json_mode: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "contents": contents
        }
        if system_instruction:
            payload["system_instruction"] = system_instruction

        generation_config: Dict[str, Any] = {}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        if "temperature" in kwargs:
            generation_config["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            generation_config["maxOutputTokens"] = kwargs["max_tokens"]

        if generation_config:
            payload["generationConfig"] = generation_config

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
        """Executa inferência direta na API generateContent do Gemini."""
        if not self.api_key:
            raise LLMAuthenticationError("Chave de API do Google Gemini não informada.")

        clean_model = self._clean_model_name(model_override or self.model)
        url = f"{self.base_url}/v1beta/models/{clean_model}:generateContent"
        params = {"key": self.api_key}
        headers = self._get_headers()

        system_instruction, contents = self._build_contents_and_system(messages, system_prompt)
        payload = self._build_payload(contents, system_instruction, json_mode=json_mode, **kwargs)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(url, json=payload, headers=headers, params=params)

                if res.status_code in (400, 401, 403):
                    err_msg = res.text
                    if "API_KEY_INVALID" in err_msg or "PERMISSION_DENIED" in err_msg or res.status_code in (401, 403):
                        raise LLMAuthenticationError(
                            f"Falha de autenticação no Google Gemini ({res.status_code}): Chave de API inválida."
                        )
                    raise LLMGatewayError(f"Erro na requisição ao Gemini ({res.status_code}): {err_msg}")

                if res.status_code == 404:
                    raise LLMModelNotFoundError(
                        f"Modelo '{clean_model}' não encontrado no Gemini ({res.status_code})."
                    )

                if res.status_code != 200:
                    raise LLMGatewayError(
                        f"Erro na API Google Gemini [{res.status_code}]: {res.text}"
                    )

                data = res.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return ""

                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts if "text" in p)

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Não foi possível conectar ao endpoint Google Gemini em {self.base_url}."
            ) from e
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(
                f"Tempo limite excedido ({timeout}s) ao aguardar resposta do Google Gemini."
            ) from e
        except LLMGatewayError:
            raise
        except Exception as e:
            raise LLMGatewayError(f"Erro inesperado no adaptador Gemini: {str(e)}") from e

    async def stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model_override: Optional[str] = None,
        timeout: float = 60.0,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Gera resposta em streaming via streamGenerateContent?alt=sse."""
        if not self.api_key:
            raise LLMAuthenticationError("Chave de API do Google Gemini não informada.")

        clean_model = self._clean_model_name(model_override or self.model)
        url = f"{self.base_url}/v1beta/models/{clean_model}:streamGenerateContent"
        params = {"alt": "sse", "key": self.api_key}
        headers = self._get_headers()

        system_instruction, contents = self._build_contents_and_system(messages, system_prompt)
        payload = self._build_payload(contents, system_instruction, json_mode=False, **kwargs)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers, params=params) as response:
                    if response.status_code in (401, 403):
                        err_text = await response.aread()
                        raise LLMAuthenticationError(
                            f"Falha de autenticação no Google Gemini ({response.status_code}): {err_text.decode('utf-8', errors='ignore')}"
                        )
                    if response.status_code != 200:
                        err_text = await response.aread()
                        raise LLMGatewayError(
                            f"Erro no streaming Gemini [{response.status_code}]: {err_text.decode('utf-8', errors='ignore')}"
                        )

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue

                        if line.startswith("data:"):
                            raw_data = line[5:].strip()
                            if raw_data == "[DONE]":
                                break

                            try:
                                chunk = json.loads(raw_data)
                            except json.JSONDecodeError:
                                continue

                            candidates = chunk.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    token = part.get("text", "")
                                    if token:
                                        yield token

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Não foi possível conectar ao endpoint Google Gemini em {self.base_url}."
            ) from e
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(
                f"Tempo limite excedido ({timeout}s) no streaming Google Gemini."
            ) from e
        except LLMGatewayError:
            raise
        except Exception as e:
            raise LLMGatewayError(f"Falha no streaming Google Gemini: {str(e)}") from e

    async def list_models(self, timeout: float = 6.0) -> List[str]:
        """Consulta /v1beta/models para listar modelos que suportam geração de conteúdo."""
        if not self.api_key:
            return self.CURATED_MODELS

        url = f"{self.base_url}/v1beta/models"
        params = {"key": self.api_key}
        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(url, headers=headers, params=params)
                if res.status_code == 200:
                    data = res.json()
                    models_raw = data.get("models", [])
                    filtered_models: List[str] = []
                    for m in models_raw:
                        methods = m.get("supportedGenerationMethods", [])
                        name = m.get("name", "")
                        if "generateContent" in methods:
                            clean = name[7:] if name.startswith("models/") else name
                            filtered_models.append(clean)
                    if filtered_models:
                        return filtered_models
        except Exception as e:
            logger.debug("Falha ao consultar modelos no Gemini (%s), usando lista curada.", str(e))

        return self.CURATED_MODELS

    async def test_connection(self, timeout: float = 6.0) -> Dict[str, Any]:
        """Valida credenciais da Google Generative Language API e lista modelos disponíveis."""
        if not self.api_key:
            return {
                "success": False,
                "message": "Chave de API do Google Gemini não fornecida.",
                "models": [],
                "details": "Obtenha uma chave no Google AI Studio (AIzaSy...) e configure nas opções."
            }

        start_time = time.perf_counter()
        url = f"{self.base_url}/v1beta/models"
        params = {"key": self.api_key}
        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(url, headers=headers, params=params)
                latency = round((time.perf_counter() - start_time) * 1000, 2)

                if res.status_code == 200:
                    data = res.json()
                    models_raw = data.get("models", [])
                    models = [
                        m["name"][7:] if m.get("name", "").startswith("models/") else m.get("name", "")
                        for m in models_raw
                        if "generateContent" in m.get("supportedGenerationMethods", [])
                    ]
                    return {
                        "success": True,
                        "message": f"Conexão com Google Gemini realizada com sucesso! ({latency}ms)",
                        "models": models or self.CURATED_MODELS,
                        "latency_ms": latency,
                        "details": f"API respondeu com {len(models)} modelo(s) disponíveis para geração."
                    }
                elif res.status_code in (400, 401, 403):
                    return {
                        "success": False,
                        "message": "Falha de autenticação no Google Gemini: Chave de API inválida.",
                        "models": [],
                        "latency_ms": latency,
                        "details": res.text
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Google Gemini retornou código HTTP {res.status_code}.",
                        "models": [],
                        "latency_ms": latency,
                        "details": res.text
                    }

        except httpx.ConnectError:
            return {
                "success": False,
                "message": f"Não foi possível conectar aos servidores do Google ({self.base_url}).",
                "models": [],
                "details": "Verifique sua conexão de rede ou regras de firewall."
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": f"Tempo limite excedido ({timeout}s) ao testar Google Gemini.",
                "models": [],
                "details": "O serviço do Google demorou a responder."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Erro inesperado ao testar Google Gemini: {str(e)}",
                "models": [],
                "details": str(e)
            }
