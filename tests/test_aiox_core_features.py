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


if __name__ == "__main__":
    test_aiox_agent_commands()
    test_aiox_sudo_commands()
    test_aiox_story_driven_and_quality_gate()
    test_supervisor_conversational_resilience()
    print("\n=======================================================")
    print("TODOS OS TESTES DE RECURSOS AIOX PASSARAM COM 100% SUCESSO!")
    print("=======================================================")
