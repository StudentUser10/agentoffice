"""
AgentOffice 2D - Testes Automatizados do Gateway Universal de LLMs Multi-Provedor
Cobre:
- Matriz completa de 11 provedores
- Adapters: Base, Ollama, OpenAI-compatible, Anthropic, Gemini
- LLMGatewayFactory e roteamento dinâmico
- Streaming assíncrono e extração de reasoning_content (DeepSeek R1)
- Separação de blocos de sistema (Anthropic, Gemini)
- Tratamento estruturado de exceções (Auth, Connection, Timeout, ModelNotFound)
- Teste de conexão em 1 clique e detecção de modelos
- Compatibilidade retroativa com LLMClient
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import httpx
from fastapi.testclient import TestClient

from backend.app import app
from backend.models import Agent, AppConfig
from backend.llm_client import LLMClient, LLMClientError
from backend.llm_gateway import (
    BaseLLMAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    GeminiAdapter,
    LLMGatewayFactory,
    get_adapter,
    LLMGatewayError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMModelNotFoundError,
)


# --- 1. Testes de Fábrica e Normalização ---

def test_gateway_factory_instantiation():
    # Testa os 11 provedores mapeados
    providers = [
        ("ollama", OllamaAdapter),
        ("openai_compatible", OpenAIAdapter),
        ("openai", OpenAIAdapter),
        ("anthropic", AnthropicAdapter),
        ("claude", AnthropicAdapter),
        ("gemini", GeminiAdapter),
        ("google", GeminiAdapter),
        ("groq", OpenAIAdapter),
        ("deepseek", OpenAIAdapter),
        ("mistral", OpenAIAdapter),
        ("together", OpenAIAdapter),
        ("openrouter", OpenAIAdapter),
        ("custom", OpenAIAdapter),
        ("desconhecido_fallback", OpenAIAdapter),
    ]

    for prov_name, expected_cls in providers:
        adapter = LLMGatewayFactory.get_adapter(prov_name)
        assert isinstance(adapter, expected_cls), f"Provedor {prov_name} deveria instanciar {expected_cls}, obteve {type(adapter)}"

    # Testa get_adapter auxiliar
    adapter2 = get_adapter("anthropic", api_key="sk-ant-test")
    assert isinstance(adapter2, AnthropicAdapter)
    assert adapter2.api_key == "sk-ant-test"


def test_gateway_factory_from_config_and_agent():
    cfg = AppConfig(
        provider="groq",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        api_keys={"groq": "gsk_secret123"}
    )
    adapter = LLMGatewayFactory.from_config(cfg)
    assert isinstance(adapter, OpenAIAdapter)
    assert adapter.provider == "groq"
    assert adapter.api_key == "gsk_secret123"
    assert adapter.model == "llama-3.3-70b-versatile"

    # Agente herdando
    agent_solo = Agent(
        id="ag-1",
        name="Solo Dev",
        title="Engineer",
        desk_id="desk-1"
    )
    adapter_agent_inherited = LLMGatewayFactory.from_agent(agent_solo, fallback_config=cfg)
    assert adapter_agent_inherited.model == "llama-3.3-70b-versatile"

    # Agente com sobrescrita de modelo específico
    agent_custom = Agent(
        id="ag-2",
        name="Specialist",
        title="AI Lead",
        desk_id="desk-2",
        model_name="deepseek-r1:70b"
    )
    adapter_agent_custom = LLMGatewayFactory.from_agent(agent_custom, fallback_config=cfg)
    assert adapter_agent_custom.model == "deepseek-r1:70b"


# --- 2. Testes do Adaptador Ollama ---

def test_ollama_adapter_generate_and_stream():
    adapter = OllamaAdapter(base_url="http://localhost:11434", model="llama3:latest")

    # Mock de generate
    async def run_generate_test():
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Olá, sou o modelo Ollama!"}
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            resp = await adapter.generate(
                messages=[{"role": "user", "content": "Olá"}],
                system_prompt="Você é prestativo"
            )
            assert resp == "Olá, sou o modelo Ollama!"
            call_payload = mock_post.call_args[1]["json"]
            assert call_payload["messages"][0]["role"] == "system"
            assert call_payload["messages"][0]["content"] == "Você é prestativo"

    asyncio.run(run_generate_test())

    # Mock de stream
    async def run_stream_test():
        class MockStreamResponse:
            status_code = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            async def aiter_lines(self):
                lines = [
                    json.dumps({"message": {"content": "Token1 "}}),
                    json.dumps({"message": {"content": "Token2"}}),
                ]
                for l in lines:
                    yield l

        with patch("httpx.AsyncClient.stream", return_value=MockStreamResponse()):
            tokens = []
            async for t in adapter.stream([{"role": "user", "content": "teste"}]):
                tokens.append(t)
            assert "".join(tokens) == "Token1 Token2"

    asyncio.run(run_stream_test())


# --- 3. Testes do Adaptador OpenAI e Provedores Compatíveis ---

def test_openai_adapter_reasoning_content_and_stream():
    """Valida extração correta de tokens e tolerância a reasoning_content (DeepSeek R1)."""
    adapter = OpenAIAdapter(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="sk-deepseek-test",
        model="deepseek-reasoner"
    )

    async def run_stream_deepseek():
        class MockStreamResponse:
            status_code = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            async def aiter_lines(self):
                # Simula SSE com reasoning_content inicial e depois content
                chunks = [
                    'data: {"choices":[{"delta":{"reasoning_content":"Pensando profundamente..."}}]}',
                    'data: {"choices":[{"delta":{"content":"Resposta"}}]}',
                    'data: {"choices":[{"delta":{"content":" final."}}]}',
                    'data: [DONE]'
                ]
                for c in chunks:
                    yield c

        with patch("httpx.AsyncClient.stream", return_value=MockStreamResponse()):
            tokens = []
            async for t in adapter.stream([{"role": "user", "content": "Resolva 2+2"}]):
                tokens.append(t)
            assert "".join(tokens) == "Resposta final."

    asyncio.run(run_stream_deepseek())


def test_openai_adapter_role_o1_conversion():
    """Valida que modelos o1/o3 convertem papel 'system' em 'developer'."""
    adapter = OpenAIAdapter(
        provider="openai",
        model="o1-mini",
        api_key="sk-test"
    )
    msgs = adapter._build_messages(
        messages=[{"role": "user", "content": "Olá"}],
        system_prompt="Regra estrita",
        model="o1-mini"
    )
    assert msgs[0]["role"] == "developer"
    assert msgs[0]["content"] == "Regra estrita"


# --- 4. Testes do Adaptador Anthropic Claude ---

def test_anthropic_adapter_messages_and_streaming():
    adapter = AnthropicAdapter(
        provider="anthropic",
        api_key="sk-ant-testkey",
        model="claude-3-5-sonnet-20241022"
    )

    # 1. Validação de formato de mensagens e extração de system
    system_out, msgs_out = adapter._prepare_messages_and_system(
        messages=[
            {"role": "system", "content": "Instrução antiga"},
            {"role": "user", "content": "Pergunta 1"},
            {"role": "user", "content": "Pergunta 2 consecutivo"}
        ],
        system_prompt="Prompt principal"
    )
    assert "Prompt principal" in system_out
    assert "Instrução antiga" in system_out
    # Consecutivas devem ter sido unificadas
    assert len(msgs_out) == 1
    assert "Pergunta 1\n\nPergunta 2 consecutivo" in msgs_out[0]["content"]

    # 2. Teste de geração não-streaming
    async def run_anthropic_gen():
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Resposta da Claude 3.5 Sonnet."}]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            out = await adapter.generate([{"role": "user", "content": "Olá"}])
            assert out == "Resposta da Claude 3.5 Sonnet."
            headers = mock_post.call_args[1]["headers"]
            assert headers["x-api-key"] == "sk-ant-testkey"
            assert headers["anthropic-version"] == "2023-06-01"

    asyncio.run(run_anthropic_gen())

    # 3. Teste de streaming SSE
    async def run_anthropic_stream():
        class MockAnthropicStream:
            status_code = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            async def aiter_lines(self):
                sse_lines = [
                    "event: message_start",
                    'data: {"type": "message_start"}',
                    "",
                    "event: content_block_delta",
                    'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Claude "}}',
                    "",
                    "event: content_block_delta",
                    'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "responde!"}}',
                    "",
                    "event: message_stop",
                    'data: {"type": "message_stop"}'
                ]
                for line in sse_lines:
                    yield line

        with patch("httpx.AsyncClient.stream", return_value=MockAnthropicStream()):
            tokens = []
            async for chunk in adapter.stream([{"role": "user", "content": "Oi"}]):
                tokens.append(chunk)
            assert "".join(tokens) == "Claude responde!"

    asyncio.run(run_anthropic_stream())


# --- 5. Testes do Adaptador Google Gemini ---

def test_gemini_adapter_generate_and_streaming():
    adapter = GeminiAdapter(
        provider="gemini",
        api_key="AIzaSyTestKey",
        model="gemini-1.5-flash"
    )

    # 1. Estruturação de contents e system_instruction
    sys_inst, contents = adapter._build_contents_and_system(
        messages=[
            {"role": "system", "content": "Seja breve"},
            {"role": "user", "content": "Qual a capital da França?"},
            {"role": "assistant", "content": "Paris."}
        ],
        system_prompt="Instrução do Sistema"
    )
    assert sys_inst["parts"][0]["text"] == "Instrução do Sistema\n\nSeja breve"
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"  # Gemini usa 'model' ao invés de 'assistant'

    # 2. Teste de generateContent
    async def run_gemini_gen():
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Resposta do Gemini 1.5 Flash."}],
                        "role": "model"
                    }
                }
            ]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            out = await adapter.generate([{"role": "user", "content": "Olá"}])
            assert out == "Resposta do Gemini 1.5 Flash."
            params = mock_post.call_args[1]["params"]
            assert params["key"] == "AIzaSyTestKey"

    asyncio.run(run_gemini_gen())

    # 3. Teste de streamGenerateContent
    async def run_gemini_stream():
        class MockGeminiStream:
            status_code = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            async def aiter_lines(self):
                sse_lines = [
                    'data: {"candidates":[{"content":{"parts":[{"text":"Gemini "}]}}]}',
                    'data: {"candidates":[{"content":{"parts":[{"text":"Stream!"}]}}]}',
                    'data: [DONE]'
                ]
                for line in sse_lines:
                    yield line

        with patch("httpx.AsyncClient.stream", return_value=MockGeminiStream()):
            tokens = []
            async for chunk in adapter.stream([{"role": "user", "content": "Oi"}]):
                tokens.append(chunk)
            assert "".join(tokens) == "Gemini Stream!"

    asyncio.run(run_gemini_stream())


# --- 6. Testes de Exceções Estruturadas ---

def test_structured_exception_handling():
    # Sem API Key
    adapter = AnthropicAdapter(api_key="")
    async def test_auth_err():
        try:
            await adapter.generate([{"role": "user", "content": "oi"}])
            assert False, "Deveria ter lançado LLMAuthenticationError"
        except LLMAuthenticationError:
            pass
    asyncio.run(test_auth_err())

    # Timeout
    adapter_groq = OpenAIAdapter(provider="groq", api_key="gsk-test")
    async def test_timeout_err():
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("timeout")):
            try:
                await adapter_groq.generate([{"role": "user", "content": "oi"}], timeout=1.0)
                assert False, "Deveria ter lançado LLMTimeoutError"
            except LLMTimeoutError:
                pass
    asyncio.run(test_timeout_err())


# --- 7. Teste de Compatibilidade Retroativa do LLMClient ---

def test_llm_client_facade_compatibility():
    cfg = AppConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model="claude-3-5-haiku-20241022",
        api_keys={"anthropic": "sk-ant-test"}
    )
    llm = LLMClient(cfg)
    assert llm.provider == "anthropic"

    # Valida chamada delegando ao adapter
    async def run_facade_test():
        with patch.object(llm.adapter, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Executado via fachada com sucesso."
            res = await llm.generate_response(
                messages=[{"role": "user", "content": "teste"}],
                system_prompt="sys prompt"
            )
            assert res == "Executado via fachada com sucesso."
            mock_gen.assert_called_once()

    asyncio.run(run_facade_test())


# --- 8. Testes dos Endpoints REST do Gateway ---

def test_api_test_connection_multi_provider():
    client = TestClient(app)

    # 1. Provedor Ollama Offline
    res = client.post("/api/config/test-connection", json={
        "provider": "ollama",
        "base_url": "http://127.0.0.1:9999"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "Não foi possível conectar" in data["message"]

    # 2. Provedor OpenAI com Sucesso Mockado
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = client.post("/api/config/test-connection", json={
            "provider": "openai",
            "api_key": "sk-proj-valid-test-key"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "gpt-4o" in data["models"]

    # 3. Provedor Anthropic sem chave
    res = client.post("/api/config/test-connection", json={
        "provider": "anthropic",
        "api_key": ""
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "não fornecida" in data["message"]

    # 4. Provedor Gemini com chave fornecida e mock
    mock_gemini_resp = MagicMock(status_code=200)
    mock_gemini_resp.json.return_value = {
        "models": [
            {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-1.5-pro", "supportedGenerationMethods": ["generateContent"]}
        ]
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_gemini_resp
        res = client.post("/api/config/test-connection", json={
            "provider": "gemini",
            "api_key": "AIzaSyValidKey"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "gemini-1.5-flash" in data["models"]


if __name__ == "__main__":
    print("Iniciando bateria de testes do Gateway Universal de LLMs...")
    print("\n--- 1. Testando LLMGatewayFactory e Normalização ---")
    test_gateway_factory_instantiation()
    test_gateway_factory_from_config_and_agent()
    print("OK: Factory e instanciação aprovadas.")

    print("\n--- 2. Testando OllamaAdapter ---")
    test_ollama_adapter_generate_and_stream()
    print("OK: OllamaAdapter geração e stream aprovados.")

    print("\n--- 3. Testando OpenAIAdapter e DeepSeek reasoning_content ---")
    test_openai_adapter_reasoning_content_and_stream()
    test_openai_adapter_role_o1_conversion()
    print("OK: OpenAIAdapter e DeepSeek R1 aprovados.")

    print("\n--- 4. Testando AnthropicAdapter ---")
    test_anthropic_adapter_messages_and_streaming()
    print("OK: AnthropicAdapter geração e stream SSE aprovados.")

    print("\n--- 5. Testando GeminiAdapter ---")
    test_gemini_adapter_generate_and_streaming()
    print("OK: GeminiAdapter geração e stream SSE aprovados.")

    print("\n--- 6. Testando Exceções Estruturadas ---")
    test_structured_exception_handling()
    print("OK: Exceções estruturadas validadas.")

    print("\n--- 7. Testando Fachada LLMClient ---")
    test_llm_client_facade_compatibility()
    print("OK: Fachada LLMClient retrocompatível validada.")

    print("\n--- 8. Testando Endpoints REST de Conexão ---")
    test_api_test_connection_multi_provider()
    print("OK: Endpoints REST testados com sucesso.")

    print("\nTODOS OS TESTES DO GATEWAY UNIVERSAL DE LLMS PASSARAM COM SUCESSO!")
