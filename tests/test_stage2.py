"""
Testes automatizados da Etapa 2 do AgentOffice 2D
Verifica modelos de hierarquia, CRUD de agentes, orquestração e desks com waypoints.
"""

import sys
import json
import asyncio
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app import app
from backend.models import AgentRoleType, AgentState, Agent
from backend.storage import storage
from backend.orchestrator import orchestrator


def test_stage2_desks_and_workspace():
    client = TestClient(app)

    # 1. Obter workspace e validar desks com waypoints
    res = client.get("/api/workspace")
    assert res.status_code == 200
    data = res.json()
    assert "desks" in data
    assert len(data["desks"]) == 6

    # Verificar que cada mesa possui seat_x, seat_y, front_x, front_y
    for desk in data["desks"]:
        assert "seat_x" in desk, f"Mesa {desk['id']} deve conter seat_x"
        assert "seat_y" in desk, f"Mesa {desk['id']} deve conter seat_y"
        assert "front_x" in desk, f"Mesa {desk['id']} deve conter front_x"
        assert "front_y" in desk, f"Mesa {desk['id']} deve conter front_y"


def test_stage2_agent_hierarchy_crud():
    client = TestClient(app)

    # Limpar agentes para teste limpo
    ws = storage.load_workspace()
    ws.agents = []
    for d in ws.desks:
        d.agent_id = None
    storage.save_workspace(ws)

    # 1. Criar um Supervisor (Tech Lead na Mesa 1)
    sup_payload = {
        "name": "Alex Tech Lead",
        "title": "Tech Lead & Arquiteto",
        "role_type": "supervisor",
        "desk_id": "desk-1",
        "system_prompt": "Você é o líder técnico responsável pelo projeto."
    }
    res = client.post("/api/agents", json=sup_payload)
    assert res.status_code == 200, f"Falha ao criar supervisor: {res.text}"
    supervisor = res.json()
    assert supervisor["role_type"] == "supervisor"
    assert supervisor["desk_id"] == "desk-1"
    sup_id = supervisor["id"]

    # 2. Criar um Worker subordinado ao Tech Lead (na Mesa 2)
    worker_payload = {
        "name": "Beatriz Backend",
        "title": "Engenheira Backend",
        "role_type": "worker",
        "supervisor_id": sup_id,
        "desk_id": "desk-2",
        "system_prompt": "Você é especialista em APIs FastAPI e bancos de dados."
    }
    res = client.post("/api/agents", json=worker_payload)
    assert res.status_code == 200, f"Falha ao criar worker: {res.text}"
    worker = res.json()
    assert worker["role_type"] == "worker"
    assert worker["supervisor_id"] == sup_id
    worker_id = worker["id"]

    # 3. Verificar que o Supervisor registrou o Worker na sua lista de subordinados
    ws_updated = storage.load_workspace()
    updated_sup = next(a for a in ws_updated.agents if a.id == sup_id)
    assert worker_id in updated_sup.subordinate_ids, "Worker deve constar em subordinate_ids do Supervisor"

    # 4. Verificar ocupação das mesas
    desk1 = next(d for d in ws_updated.desks if d.id == "desk-1")
    desk2 = next(d for d in ws_updated.desks if d.id == "desk-2")
    assert desk1.agent_id == sup_id
    assert desk2.agent_id == worker_id

    # 5. Tentativa de ocupar mesa já ocupada deve retornar erro 400
    conflict_payload = {
        "name": "Intruso",
        "title": "Estagiário",
        "role_type": "solo",
        "desk_id": "desk-1"
    }
    res = client.post("/api/agents", json=conflict_payload)
    assert res.status_code == 400

    # 6. Atualizar agente
    update_payload = {
        "title": "Tech Lead Sênior"
    }
    res = client.put(f"/api/agents/{sup_id}", json=update_payload)
    assert res.status_code == 200
    assert res.json()["title"] == "Tech Lead Sênior"

    # 7. Excluir o Worker e verificar desvinculação
    res = client.delete(f"/api/agents/{worker_id}")
    assert res.status_code == 200
    ws_after_del = storage.load_workspace()
    updated_sup2 = next(a for a in ws_after_del.agents if a.id == sup_id)
    assert worker_id not in updated_sup2.subordinate_ids, "Subordinado excluído deve ser removido do supervisor"
    desk2_after = next(d for d in ws_after_del.desks if d.id == "desk-2")
    assert desk2_after.agent_id is None, "Mesa deve ser liberada após exclusão do agente"


def test_stage2_orchestrator_json_parsing():
    # Testar parsing com JSON limpo
    clean_json = '{"plan_summary": "Plano A", "subtasks": [{"worker_id": "w1", "task": "tarefa 1"}]}'
    parsed = orchestrator._extract_json(clean_json, [])
    assert parsed["plan_summary"] == "Plano A"
    assert len(parsed["subtasks"]) == 1

    # Testar parsing com markdown code block
    md_json = 'Aqui está o plano:\n```json\n{"plan_summary": "Plano B", "subtasks": [{"worker_id": "w2", "task": "tarefa 2"}]}\n```\nFim.'
    parsed_md = orchestrator._extract_json(md_json, [])
    assert parsed_md["plan_summary"] == "Plano B"

    # Testar fallback quando JSON for inválido
    dummy_worker = Agent(
        id="worker-99",
        name="Dev",
        title="Coder",
        avatar_id="avatar_1",
        desk_id="desk-3"
    )
    fallback = orchestrator._extract_json("Texto sem formato json algum", [dummy_worker])
    assert "subtasks" in fallback
    assert len(fallback["subtasks"]) == 1
    assert fallback["subtasks"][0]["worker_id"] == "worker-99"


if __name__ == "__main__":
    print("Executando test_stage2_desks_and_workspace...")
    test_stage2_desks_and_workspace()
    print("Executando test_stage2_agent_hierarchy_crud...")
    test_stage2_agent_hierarchy_crud()
    print("Executando test_stage2_orchestrator_json_parsing...")
    test_stage2_orchestrator_json_parsing()
    print("\nTODOS OS TESTES DA ETAPA 2 PASSARAM COM SUCESSO!")
