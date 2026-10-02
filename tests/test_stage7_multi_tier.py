"""
AgentOffice 2D - Testes Automatizados da Etapa 7: Arquitetura Multinível
(Sudo Agent, Departamentos, Líderes de Squad & Comunicação Lateral Inter-Squad)

Validações:
1. Modelagem Pydantic: AgentTier, Squad, CrossSquadTicket, AgentConfig, DispatchToSquadParams, RequestCrossSquadParams.
2. Ferramenta exclusiva Sudo: dispatch_to_squad com difusão de eventos.
3. Ferramenta lateral de Líderes: request_cross_squad_help com persistência de ticket e trânsito físico.
4. Resolução de tickets: resolve_cross_squad_ticket com entrega de artefatos.
5. MultiTierOrchestrator: Ciclo completo do cenário real:
   - Usuário solicita API com SQLite + auditoria de vulnerabilidades.
   - Sudo Agent delega para Squad de Engenharia e audita critérios globais.
   - Líder de Engenharia detecta falta de competência interna de segurança e aciona Squad de Segurança.
   - Squad de Segurança processa ticket e devolve parecer de vulnerabilidades.
   - Código sandbox gravado: src/database.py e src/routers/users.py.
   - Sudo Agent consolida as entregas em parecer executivo final.
6. Endpoints REST da API FastAPI (/api/sudo/chat, /api/tickets, /api/tickets/{id}/resolve).
"""

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import app
from backend.models import (
    Agent,
    AgentConfig,
    AgentRoleType,
    AgentState,
    AgentTier,
    CrossSquadTicket,
    Desk,
    DispatchToSquadParams,
    RequestCrossSquadParams,
    Squad,
    WorkspaceData,
)
from backend.orchestrator_multi_tier import (
    MultiTierOrchestrator,
    multi_tier_orchestrator,
)
from backend.storage import storage
from backend.tools.squad_tools import (
    dispatch_to_squad,
    list_active_tickets,
    request_cross_squad_help,
    resolve_cross_squad_ticket,
)


def setup_temp_workspace():
    """Configura um diretório temporário isolado como sandbox para os testes."""
    temp_dir = tempfile.mkdtemp(prefix="agentoffice_tier_test_")
    cfg = storage.load_config()
    cfg.workspace_dir = temp_dir
    cfg.configured = True
    storage.save_config(cfg)
    return Path(temp_dir)


def teardown_temp_workspace(temp_dir: Path):
    """Limpa o diretório temporário."""
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


# --- 1. Testes de Modelagem de Dados ---

def test_models_agent_tier_and_config():
    """Valida o enum AgentTier e o modelo AgentConfig exigidos na especificação."""
    assert AgentTier.SUDO == "sudo"
    assert AgentTier.SQUAD_LEADER == "squad_leader"
    assert AgentTier.WORKER == "worker"
    assert AgentTier.SUBAGENT == "subagent"

    config = AgentConfig(
        id="agent-sudo",
        name="Sudo Agent",
        tier=AgentTier.SUDO,
        desk_id="desk-sudo",
        room_id="room_sudo",
        avatar_id="avatar_sudo",
        model_name="llama3:latest",
        system_prompt="Diretoria Geral",
        status="idle"
    )
    assert config.id == "agent-sudo"
    assert config.tier == AgentTier.SUDO
    assert config.squad_id is None
    assert config.room_id == "room_sudo"


def test_models_squad_and_cross_squad_ticket():
    """Valida modelos Squad e CrossSquadTicket."""
    squad = Squad(
        id="squad-security",
        name="Squad de Segurança Cibernética",
        room_id="room_sec",
        leader_id="agent-sec-lead",
        member_ids=["agent-sec-lead", "agent-sec-analyst"],
        domain_tags=["security", "audit", "owasp", "cryptography"],
        color_theme="#a855f7"
    )
    assert squad.room_id == "room_sec"
    assert squad.color_theme == "#a855f7"
    assert "security" in squad.domain_tags

    ticket = CrossSquadTicket(
        from_squad_id="squad-core-engineering",
        to_squad_id="squad-security",
        requesting_leader_id="agent-dev-lead",
        reason_out_of_scope="Falta de competência interna para auditoria de vulnerabilidades",
        exact_requirement="Auditar rotas FastAPI contra injeção SQL e falhas de CORS",
        status="pending"
    )
    assert ticket.status == "pending"
    assert ticket.result_artifact is None
    assert len(ticket.ticket_id) > 10


def test_models_tool_params():
    """Valida os esquemas de validação de ferramentas dispatch_to_squad e request_cross_squad_help."""
    dispatch_params = DispatchToSquadParams(
        target_squad_id="squad-core-engineering",
        epic_title="Criação da API de Usuários",
        objective="Construir rotas FastAPI e banco SQLite",
        acceptance_criteria="Código executável e tipado"
    )
    assert dispatch_params.target_squad_id == "squad-core-engineering"

    cross_params = RequestCrossSquadParams(
        target_squad_id="squad-security",
        reason_why_needed="Não temos equipe de sec interna",
        what_exact_service="Auditar rotas contra OWASP Top 10",
        how_format_response="Relatório Markdown estruturado"
    )
    assert cross_params.target_squad_id == "squad-security"


# --- 2. Testes de Ferramentas de Squad e Tickets ---

def test_squad_tools_dispatch_and_tickets():
    """Valida o ciclo de despacho e abertura/resolução de tickets inter-squad."""
    temp_dir = setup_temp_workspace()
    try:
        ws = storage.load_workspace()

        # Assegurar agentes nos papéis corretos
        sudo = next((a for a in ws.agents if a.tier == AgentTier.SUDO), None)
        if not sudo:
            sudo = Agent(
                id="agent-sudo",
                name="Sudo Agent",
                title="Diretor Geral",
                tier=AgentTier.SUDO,
                desk_id="desk-sudo",
                room_id="room_sudo"
            )
            ws.agents.append(sudo)

        dev_lead = next((a for a in ws.agents if a.tier == AgentTier.SQUAD_LEADER and a.room_id == "room_dev"), None)
        if not dev_lead:
            dev_lead = Agent(
                id="agent-dev-lead",
                name="Dev Lead",
                title="Líder de Engenharia",
                tier=AgentTier.SQUAD_LEADER,
                squad_id="squad-core-engineering",
                desk_id="desk-1",
                room_id="room_dev"
            )
            ws.agents.append(dev_lead)

        sec_lead = next((a for a in ws.agents if a.tier == AgentTier.SQUAD_LEADER and a.room_id == "room_sec"), None)
        if not sec_lead:
            sec_lead = Agent(
                id="agent-sec-lead",
                name="Sec Lead",
                title="Líder de Segurança",
                tier=AgentTier.SQUAD_LEADER,
                squad_id="squad-security",
                desk_id="desk-sec-1",
                room_id="room_sec"
            )
            ws.agents.append(sec_lead)

        storage.save_workspace(ws)

        # 1. Testar dispatch_to_squad
        dispatch_res = asyncio.run(
            dispatch_to_squad(
                target_squad_id="squad-core-engineering",
                epic_title="API de Usuários com SQLite",
                objective="Desenvolver backend simples com SQLite",
                acceptance_criteria="Rotas de listagem e criação funcionando",
                sudo_agent_id=sudo.id,
                workspace=ws
            )
        )
        assert "sucesso" in dispatch_res.lower()

        # 2. Testar request_cross_squad_help
        ticket, msg = asyncio.run(
            request_cross_squad_help(
                requesting_leader_id=dev_lead.id,
                target_squad_id="squad-security",
                reason_why_needed="Engenharia não possui escopo para auditoria criptográfica",
                what_exact_service="Auditar rotas contra SQL Injection",
                how_format_response="Parecer Markdown",
                workspace=ws
            )
        )
        assert ticket.status == "pending"
        assert ticket.requesting_leader_id == dev_lead.id

        # 3. Listar tickets ativos
        active_tickets = list_active_tickets(ws)
        assert len(active_tickets) >= 1
        assert any(t.ticket_id == ticket.ticket_id for t in active_tickets)

        # 4. Resolver ticket
        resolved = asyncio.run(
            resolve_cross_squad_ticket(
                ticket_id=ticket.ticket_id,
                result_artifact="### Parecer de Segurança: Aprovado sem vulnerabilidades.",
                workspace=ws
            )
        )
        assert resolved is True
        assert ticket.status == "delivered"
        assert "Aprovado" in ticket.result_artifact

    finally:
        teardown_temp_workspace(temp_dir)


# --- 3. Teste End-to-End do Cenário Real (MultiTierOrchestrator) ---

def test_multi_tier_orchestrator_scenario():
    """
    Simula o cenário do roteiro de validação:
    1. Usuário envia ao Sudo Agent: 'Desenvolva uma API simples de usuários com banco SQLite e faça uma análise de vulnerabilidades de segurança das rotas criadas'
    2. Sudo Agent delega criação da API para Engenharia e auditoria para Segurança.
    3. Líder de Engenharia aciona Segurança via request_cross_squad_help.
    4. Squad de Segurança processa o ticket e devolve o parecer.
    5. Arquivos são criados no sandbox.
    6. Sudo Agent consolida o resumo geral.
    """
    temp_dir = setup_temp_workspace()
    try:
        prompt = "Desenvolva uma API simples de usuários com banco SQLite e faça uma análise de vulnerabilidades de segurança das rotas criadas"

        res = asyncio.run(
            multi_tier_orchestrator.handle_sudo_macro_goal(prompt)
        )

        assert res["status"] == "success"
        assert len(res["dispatches"]) >= 1
        assert len(res["squad_deliveries"]) >= 1
        assert "🏛️ PARECER EXECUTIVO" in res["final_executive_summary"]
        assert "DIRETORIA" in res["final_executive_summary"]

        # Verificar se os arquivos sandbox foram de fato gravados
        db_file = temp_dir / "src" / "database.py"
        router_file = temp_dir / "src" / "routers" / "users.py"

        assert db_file.exists(), "src/database.py deveria ter sido criado no sandbox"
        assert router_file.exists(), "src/routers/users.py deveria ter sido criado no sandbox"

        db_content = db_file.read_text(encoding="utf-8")
        assert "sqlite" in db_content.lower()

        router_content = router_file.read_text(encoding="utf-8")
        assert "fastapi" in router_content.lower()
        assert "user" in router_content.lower()

    finally:
        teardown_temp_workspace(temp_dir)


# --- 4. Testes dos Endpoints REST FastAPI ---

def test_api_sudo_endpoints():
    """Valida os endpoints REST da Diretoria e dos Tickets."""
    temp_dir = setup_temp_workspace()
    client = TestClient(app)
    try:
        # 1. GET /api/tickets inicial
        res = client.get("/api/tickets")
        assert res.status_code == 200
        tickets = res.json()
        assert isinstance(tickets, list)

        # 2. POST /api/sudo/chat
        res_sudo = client.post("/api/sudo/chat", json={
            "message": "Crie um serviço de usuários com SQLite e valide a segurança"
        })
        assert res_sudo.status_code == 200
        data = res_sudo.json()
        assert data["status"] in ["started", "success"]

        # 3. GET /api/tickets após execução
        res_tickets = client.get("/api/tickets")
        assert res_tickets.status_code == 200
        active_tickets = res_tickets.json()
        assert isinstance(active_tickets, list)

        # 4. POST /api/tickets/{ticket_id}/resolve
        if active_tickets:
            ticket_id = active_tickets[0]["ticket_id"]
            res_resolve = client.post(f"/api/tickets/{ticket_id}/resolve", json={
                "result_artifact": "Parecer técnico auditado e conforme."
            })
            assert res_resolve.status_code == 200
            assert res_resolve.json().get("status") == "resolved"

        # 5. POST /api/chat com Sudo Agent direciona para o orquestrador multinível
        ws = storage.load_workspace()
        sudo = next((a for a in ws.agents if getattr(a, "tier", None) == AgentTier.SUDO), None)
        if sudo:
            res_chat_sudo = client.post("/api/chat", json={
                "agent_id": sudo.id,
                "message": "Planeje a nova infraestrutura corporativa"
            })
            assert res_chat_sudo.status_code == 200
            assert res_chat_sudo.json().get("status") == "started"

    finally:
        teardown_temp_workspace(temp_dir)


if __name__ == "__main__":
    print("Executando Teste 1: Modelos de Dados & Configs...")
    test_models_agent_tier_and_config()
    test_models_squad_and_cross_squad_ticket()
    test_models_tool_params()
    print("  -> Teste 1 Concluído!")

    print("Executando Teste 2: Ferramentas de Despacho e Tickets Inter-Squad...")
    test_squad_tools_dispatch_and_tickets()
    print("  -> Teste 2 Concluído!")

    print("Executando Teste 3: MultiTierOrchestrator (Cenário E2E de Auditoria e API)...")
    test_multi_tier_orchestrator_scenario()
    print("  -> Teste 3 Concluído!")

    print("Executando Teste 4: Endpoints REST FastAPI (/api/sudo/chat, /api/tickets)...")
    test_api_sudo_endpoints()
    print("  -> Teste 4 Concluído!")

    print("\n=======================================================")
    print("TODOS OS TESTES DA ETAPA 7 PASSARAM COM 100% DE SUCESSO!")
    print("=======================================================\n")

