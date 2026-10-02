"""
Teste automatizado para garantir que:
1. O Sudo Agent responda diretamente a perguntas conversacionais e saudações ("oi, como ta por ai?"),
   salvando a conversa no histórico e disparando os eventos de finalização do chat (sem ficar travado em ●●●).
2. O endpoint de edição de agentes (PUT /api/agents/{id}) atualize corretamente nome, cargo, tier,
   squad_id, mesa e prompt, sincronizando com os squads.
"""

import asyncio
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from backend.app import app
from backend.models import AgentTier, WorkspaceData
from backend.storage import storage
from backend.orchestrator_multi_tier import multi_tier_orchestrator

client = TestClient(app)

def test_sudo_conversational_response():
    print("\n--- Testando Resposta Conversacional do Sudo Agent ---")
    workspace = storage.load_workspace()
    sudo = next((a for a in workspace.agents if a.tier == AgentTier.SUDO or a.id == "agent-sudo"), None)
    assert sudo is not None, "Sudo agent deve existir no workspace."

    # Testar pergunta conversacional "oi, como ta por ai?"
    res = asyncio.run(multi_tier_orchestrator.handle_sudo_macro_goal("oi, como ta por ai?"))
    assert res["status"] == "success"
    assert res.get("mode") == "conversational"
    assert "reply" in res and len(res["reply"]) > 10
    print(f"  -> Resposta do Sudo Agent: {res['reply'][:100]}...")

    # Verificar se foi salvo no histórico de conversas do workspace
    updated_ws = storage.load_workspace()
    convs = updated_ws.conversations.get(sudo.id, [])
    assert len(convs) >= 2, "A conversa do Sudo Agent deve conter a mensagem do usuário e a resposta."
    last_user = next((c for c in reversed(convs) if c["role"] == "user"), None)
    last_asst = next((c for c in reversed(convs) if c["role"] == "assistant"), None)
    assert last_user is not None and "oi, como ta" in last_user["text"]
    assert last_asst is not None and len(last_asst["text"]) > 10
    print("  -> Mensagens do usuário e do Sudo Agent devidamente salvas no histórico de conversas!")


def test_agent_update_endpoint():
    print("\n--- Testando Endpoint de Edição de Agentes ---")
    workspace = storage.load_workspace()
    target_agent = workspace.agents[0]
    agent_id = target_agent.id

    payload = {
        "name": f"{target_agent.name} (Editado)",
        "title": "Lead Architect & Strategist",
        "tier": "squad_leader",
        "role_type": "supervisor",
        "desk_id": target_agent.desk_id,
        "squad_id": "squad-core-engineering",
        "system_prompt": "Prompt customizado de teste para edição.",
        "model_name": "llama3:latest"
    }

    res = client.put(f"/api/agents/{agent_id}", json=payload)
    assert res.status_code == 200, f"Falha ao atualizar agente: {res.text}"
    data = res.json()

    assert data["name"] == payload["name"]
    assert data["title"] == payload["title"]
    assert data["tier"] == "squad_leader"
    assert data["squad_id"] == "squad-core-engineering"
    assert data["system_prompt"] == payload["system_prompt"]
    assert data["model_name"] == payload["model_name"]
    print(f"  -> Agente {agent_id} atualizado com sucesso no endpoint!")

    # Verificar sincronização com squads.json
    squads_data = storage.load_squads()
    eng_squad = next((s for s in squads_data.squads if s.id == "squad-core-engineering"), None)
    assert eng_squad is not None
    assert agent_id in eng_squad.member_ids
    assert eng_squad.leader_id == agent_id
    print("  -> Sincronização com o Squad de Engenharia validada com sucesso!")


if __name__ == "__main__":
    test_sudo_conversational_response()
    test_agent_update_endpoint()
    print("\n=======================================================")
    print("TODOS OS TESTES DE FEEDBACK E EDIÇÃO PASSARAM COM SUCESSO!")
    print("=======================================================")
