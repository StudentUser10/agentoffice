"""
AgentOffice 2D - Teste Automatizado das Melhorias e Arquitetura AIOX-Core
Valida:
1. AIOX Command Engine (*help, *status, *qa, *rules, *plan) para agentes e Sudo Agent.
2. AIOX Story-Driven Architecture: Geração de stories/ com Acceptance Criteria e reports/ com QA Quality Gate.
3. AIOX Audit Trail: Registro imutável de operações de arquivo em .aiox_audit.jsonl.
4. Resiliência do Supervisor: Mensagens conversacionais com supervisores não quebram em JSON HTTP 400.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from backend.app import app
from backend.models import AgentRoleType, AgentTier
from backend.storage import storage
from backend.orchestrator import orchestrator
from backend.orchestrator_multi_tier import multi_tier_orchestrator
from backend.tools.filesystem import _get_workspace_dir, aiox_validate_code_syntax

client = TestClient(app)


def test_aiox_agent_commands():
    print("\n--- Testando AIOX Command Engine em Agentes de Squad ---")
    workspace = storage.load_workspace()
    alex = next((a for a in workspace.agents if a.id == "agent-1c137c"), None)
    assert alex is not None, "Alex Tech Lead deve existir no workspace."

    # 1. Testar comando *help
    asyncio.run(orchestrator.execute_task(alex.id, "*help"))
    updated_ws = storage.load_workspace()
    convs = updated_ws.conversations.get(alex.id, [])
    assert len(convs) >= 2
    last_reply = convs[-1]["text"]
    assert "Matriz de Recursos AIOX" in last_reply
    assert "*help" in last_reply and "*qa" in last_reply and "*rules" in last_reply
    print("  -> *help executado com sucesso e retornou matriz AIOX!")

    # 2. Testar comando *status
    asyncio.run(orchestrator.execute_task(alex.id, "*status"))
    updated_ws = storage.load_workspace()
    last_reply = updated_ws.conversations[alex.id][-1]["text"]
    assert "Status Operacional AIOX" in last_reply
    assert "Squad / Sala" in last_reply
    print("  -> *status executado com sucesso!")

    # 3. Testar comando *rules
    asyncio.run(orchestrator.execute_task(alex.id, "*rules"))
    updated_ws = storage.load_workspace()
    last_reply = updated_ws.conversations[alex.id][-1]["text"]
    assert "Manifesto do Squad" in last_reply
    assert "Definition of Done" in last_reply
    print("  -> *rules executado com sucesso!")


def test_aiox_sudo_commands():
    print("\n--- Testando AIOX Command Engine no Sudo Agent ---")
    workspace = storage.load_workspace()
    sudo = next((a for a in workspace.agents if a.tier == AgentTier.SUDO or a.id == "agent-sudo"), None)
    assert sudo is not None, "Sudo Agent deve existir."

    res = asyncio.run(multi_tier_orchestrator.handle_sudo_macro_goal("*help", workspace))
    assert res["status"] == "success"
    assert res["mode"] == "aiox_command"
    assert "Matriz Executiva AIOX" in res["reply"]
    assert "Governança" in res["reply"]
    print(f"  -> Sudo *help validado com sucesso!")

    res_status = asyncio.run(multi_tier_orchestrator.handle_sudo_macro_goal("*status", workspace))
    assert res_status["status"] == "success"
    assert "Painel Corporativo AIOX" in res_status["reply"]
    print(f"  -> Sudo *status validado com sucesso!")


def test_aiox_story_driven_and_quality_gate():
    print("\n--- Testando Ciclo Story-Driven & QA Quality Gate (AIOX) ---")
    ws_root = _get_workspace_dir()

    # Executar meta macro de criação de API
    macro_prompt = "Desenvolva uma API simples de usuários com banco SQLite e rotas FastAPI"
    res = asyncio.run(multi_tier_orchestrator.handle_sudo_macro_goal(macro_prompt))
    assert res["status"] == "success"

    # 1. Validar que a história AIOX foi gerada em stories/
    stories_dir = ws_root / "stories"
    assert stories_dir.exists(), "Diretório stories/ deve ter sido criado no sandbox."
    story_files = list(stories_dir.glob("STORY-*.md"))
    assert len(story_files) > 0, "Deve haver pelo menos um arquivo de história gerado."
    story_content = story_files[0].read_text(encoding="utf-8")
    assert "[AIOX STORY]" in story_content
    assert "Critérios de Aceite" in story_content
    assert "Definition of Done" in story_content
    print(f"  -> História AIOX validada com sucesso: '{story_files[0].name}'!")

    # 2. Validar que o código foi gravado no sandbox
    db_file = ws_root / "src" / "database.py"
    users_file = ws_root / "src" / "routers" / "users.py"
    assert db_file.exists(), "src/database.py deve existir no sandbox."
    assert users_file.exists(), "src/routers/users.py deve existir no sandbox."

    # 3. Validar Quality Gate e Relatório de Conformidade
    reports_dir = ws_root / "reports"
    assert reports_dir.exists(), "Diretório reports/ deve existir no sandbox."
    qa_reports = list(reports_dir.glob("QA-REPORT-*.md"))
    assert len(qa_reports) > 0, "Deve haver pelo menos um relatório de QA gerado."
    qa_content = qa_reports[0].read_text(encoding="utf-8")
    assert "AIOX QUALITY GATE REPORT" in qa_content
    assert "APROVADO" in qa_content
    print(f"  -> Relatório de Quality Gate validado com sucesso: '{qa_reports[0].name}'!")

    # 4. Validar o log de auditoria imutável AIOX (.aiox_audit.jsonl)
    audit_file = ws_root / ".aiox_audit.jsonl"
    assert audit_file.exists(), "Arquivo de auditoria .aiox_audit.jsonl deve existir."
    audit_lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) >= 2, "Auditoria deve conter registros de criação de arquivos."
    last_audit = json.loads(audit_lines[-1])
    assert "action" in last_audit and "path" in last_audit and "timestamp" in last_audit
    print(f"  -> Log de auditoria AIOX (.aiox_audit.jsonl) com {len(audit_lines)} eventos registrados!")


def test_supervisor_conversational_resilience():
    print("\n--- Testando Resiliência Conversacional do Supervisor ---")
    workspace = storage.load_workspace()
    alex = next((a for a in workspace.agents if a.id == "agent-1c137c"), None)
    assert alex is not None and alex.role_type == AgentRoleType.SUPERVISOR

    # Enviar saudação simples que anteriormente provocava HTTP 400 no Groq com json_mode
    asyncio.run(orchestrator.execute_task(alex.id, "ola amigo, como estao as coisas no squad?"))
    updated_ws = storage.load_workspace()
    convs = updated_ws.conversations.get(alex.id, [])
    last_reply = convs[-1]["text"]
    assert len(last_reply) > 5, "Supervisor deve responder sem erro."
    assert "Falha na execução: Provedor" not in last_reply, "Não deve haver erro de JSON do LLM."
    print(f"  -> Supervisor respondeu com sucesso: {last_reply[:90]}...")
    print("  -> Resiliência contra JSON HTTP 400 validada!")


def test_aiox_memory_layer_endpoints():
    print("\n--- Testando Endpoints REST da Camada de Memória AIOX ---")
    # 1. Obter Decisões (ADRs)
    res_dec = client.get("/api/memory/decisions")
    assert res_dec.status_code == 200
    decisions = res_dec.json()
    assert len(decisions) >= 3
    assert any(d["id"] == "ADR-001" for d in decisions)
    print(f"  -> {len(decisions)} Decisões Arquiteturais (ADRs) listadas!")

    # 2. Obter Gotchas
    res_got = client.get("/api/memory/gotchas")
    assert res_got.status_code == 200
    gotchas = res_got.json()
    assert len(gotchas) >= 2
    assert any("Groq" in g["title"] for g in gotchas)
    print(f"  -> {len(gotchas)} Armadilhas conhecidas listadas!")

    # 3. Gravar nova decisão
    new_dec_payload = {
        "category": "decision",
        "title": "JWT Auth com Algoritmo EdDSA",
        "content": "Utilizar tokens JWT assinados com chaves assimétricas EdDSA.",
        "author": "Roberto do cyber",
        "tags": ["auth", "security", "jwt"]
    }
    res_post = client.post("/api/memory", json=new_dec_payload)
    assert res_post.status_code == 200
    data = res_post.json()
    assert data["title"] == new_dec_payload["title"]
    assert "ADR-" in data["id"]
    print(f"  -> Nova decisão '{data['id']}' gravada com sucesso!")

    # 4. Executar Auto-Crítica ADE
    res_crit = client.post("/api/memory/critique", json={"target_dir": "src"})
    assert res_crit.status_code == 200
    crit_data = res_crit.json()
    assert "score" in crit_data and "verdict" in crit_data
    print(f"  -> ADE Self-Critique endpoint validado: {crit_data['verdict']} (Score {crit_data['score']}/100)!")


def test_aiox_squad_yaml_export_and_import():
    print("\n--- Testando Exportação e Importação de Squads em YAML (AIOX Manifest) ---")
    # 1. Exportar Squad Core Engineering em YAML
    res_export = client.get("/api/squads/squad-core-engineering/export-yaml")
    assert res_export.status_code == 200
    export_data = res_export.json()
    assert "yaml_manifest" in export_data
    yaml_text = export_data["yaml_manifest"]
    assert "kind: aiox-squad" in yaml_text
    assert "squad-core-engineering" in yaml_text
    print("  -> Exportação de squad.yaml concluída com sucesso!")

    # 2. Importar um novo Squad via squad.yaml
    sample_yaml = """
version: "1.0"
kind: aiox-squad
metadata:
  name: Squad Data & Analytics
  id: squad-data-analytics
  room_id: room_doc
  color_theme: "#f59e0b"
  tags:
    - data
    - pandas
    - etl
    - duckdb
  description: Squad especializado em pipelines de dados e analytics.
spec:
  leader: agent-1c137c
  members:
    - agent-1c137c
    - agent-9debfa
  quality_gates:
    - ast_syntax
    - ade_critique
"""
    res_import = client.post("/api/squads/import-yaml", json={"yaml_text": sample_yaml})
    assert res_import.status_code == 200
    import_data = res_import.json()
    assert import_data["status"] == "imported"
    assert import_data["squad"]["id"] == "squad-data-analytics"
    print("  -> Importação de novo squad via squad.yaml validada com sucesso!")


def test_aiox_memory_chat_commands():
    print("\n--- Testando Comandos de Memória AIOX no Chat ---")
    workspace = storage.load_workspace()
    alex = next((a for a in workspace.agents if a.id == "agent-1c137c"), None)

    # 1. Testar *decisions
    asyncio.run(orchestrator.execute_task(alex.id, "*decisions"))
    updated_ws = storage.load_workspace()
    reply = updated_ws.conversations[alex.id][-1]["text"]
    assert "Decisões Arquiteturais Registradas" in reply
    assert "ADR-001" in reply
    print("  -> Comando *decisions executado com sucesso!")

    # 2. Testar *gotchas
    asyncio.run(orchestrator.execute_task(alex.id, "*gotchas"))
    updated_ws = storage.load_workspace()
    reply = updated_ws.conversations[alex.id][-1]["text"]
    assert "Armadilhas Conhecidas" in reply
    assert "GOTCHA-" in reply
    print("  -> Comando *gotchas executado com sucesso!")

    # 3. Testar *critique
    asyncio.run(orchestrator.execute_task(alex.id, "*critique"))
    updated_ws = storage.load_workspace()
    reply = updated_ws.conversations[alex.id][-1]["text"]
    assert "ADE SELF-CRITIQUE REPORT" in reply
    print("  -> Comando *critique executado com sucesso!")

    # 4. Testar *remember
    asyncio.run(orchestrator.execute_task(alex.id, "*remember gotcha SQLite Concurrency: Usar timeout de conexao"))
    updated_ws = storage.load_workspace()
    reply = updated_ws.conversations[alex.id][-1]["text"]
    assert "registrada" in reply
    print("  -> Comando *remember executado com sucesso!")


def test_groq_tool_use_failed_resilience():
    print("\n--- Testando Resiliência contra Erro Groq tool_use_failed ---")
    from backend.llm_gateway.openai_adapter import OpenAIAdapter
    from unittest.mock import patch, AsyncMock
    import httpx

    adapter = OpenAIAdapter(provider="groq", base_url="https://api.groq.com/openai/v1", api_key="fake-key", model="llama3-70b-8192")

    mock_resp = httpx.Response(
        status_code=400,
        json={"error": {"message": "Tool choice is none, but model called a tool", "type": "invalid_request_error", "code": "tool_use_failed", "failed_generation": '{"name": "fs_list_directory", "arguments": {"path": ""}}'}},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = asyncio.run(adapter.generate(messages=[{"role": "user", "content": "listar arquivos"}]))
        assert "fs_list_directory" in result
        print("  -> failed_generation recuperado com sucesso sem abortar o fluxo!")


def test_aiox_mention_routing():
    print("\n--- Testando Roteamento Inteligente de Menções AIOX (@handle) ---")
    # 1. Menção @dev
    res_dev = client.post("/api/chat", json={"agent_id": "agent-sudo", "message": "@dev implemente rota de ping"})
    assert res_dev.status_code == 200
    assert res_dev.json()["agent_id"] == "agent-9debfa"
    print("  -> Menção @dev roteada cirurgicamente para Dex (agent-9debfa)!")

    # 2. Menção @architect
    res_arch = client.post("/api/chat", json={"agent_id": "agent-sudo", "message": "@architect valide o blueprint"})
    assert res_arch.status_code == 200
    assert res_arch.json()["agent_id"] == "agent-1c137c"
    print("  -> Menção @architect roteada cirurgicamente para Aria (agent-1c137c)!")

    # 3. Menção @qa
    res_qa = client.post("/api/chat", json={"agent_id": "agent-sudo", "message": "@qa audite os relatórios"})
    assert res_qa.status_code == 200
    assert res_qa.json()["agent_id"] == "agent-qa"
    print("  -> Menção @qa roteada cirurgicamente para Quinn (agent-qa)!")


if __name__ == "__main__":
    test_aiox_agent_commands()
    test_aiox_sudo_commands()
    test_aiox_story_driven_and_quality_gate()
    test_supervisor_conversational_resilience()
    test_groq_tool_use_failed_resilience()
    test_aiox_memory_layer_endpoints()
    test_aiox_squad_yaml_export_and_import()
    test_aiox_memory_chat_commands()
    test_aiox_mention_routing()
    print("\n=======================================================")
    print("TODOS OS TESTES AVANÇADOS AIOX PASSARAM COM 100% SUCESSO!")
    print("=======================================================")



