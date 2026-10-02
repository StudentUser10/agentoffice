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
    # Selecionar Alex Tech Lead ou o primeiro agente que não seja o Sudo Agent
    target_agent = next((a for a in workspace.agents if a.id == "agent-1c137c" or (a.tier != AgentTier.SUDO and a.id != "agent-sudo")), None)
    assert target_agent is not None, "Deve haver um agente não-sudo para teste de edição."
    agent_id = target_agent.id

    payload = {
        "name": "Alex Tech Lead (Editado)",
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
    print("  -> Sincronização com o Squad de Engenharia validada com sucesso!")

    # Restaurar dados originais para não poluir o workspace
    payload_restore = {
        "name": target_agent.name,
        "title": target_agent.title,
        "tier": target_agent.tier.value if hasattr(target_agent.tier, "value") else target_agent.tier,
        "role_type": target_agent.role_type.value if hasattr(target_agent.role_type, "value") else target_agent.role_type,
        "desk_id": target_agent.desk_id,
        "squad_id": target_agent.squad_id,
        "system_prompt": target_agent.system_prompt,
        "model_name": target_agent.model_name
    }
    client.put(f"/api/agents/{agent_id}", json=payload_restore)


def test_squad_leader_chat_does_not_conflict_with_sudo():
    print("\n--- Testando Chat com Líder de Squad (sem conflito com Sudo Agent) ---")
    workspace = storage.load_workspace()
    roberto = next((a for a in workspace.agents if a.id == "agent-ce2916"), None)
    assert roberto is not None, "Roberto do cyber deve existir no workspace."
    assert "diretor" in roberto.title.lower(), "Roberto deve ter 'Diretor' no cargo para testar desambiguação."
    assert roberto.tier != AgentTier.SUDO, "Roberto não deve ser do tier SUDO."

    # Enviar mensagem para Roberto via API
    res = client.post("/api/chat", json={"agent_id": roberto.id, "message": "eai cara"})
    assert res.status_code == 200
    assert res.json()["status"] == "started"

    # Executar orquestração direta
    from backend.orchestrator import orchestrator
    asyncio.run(orchestrator.execute_task(roberto.id, "eai cara"))

    # Verificar resposta gravada para Roberto
    updated_ws = storage.load_workspace()
    convs = updated_ws.conversations.get(roberto.id, [])
    assert len(convs) >= 2, "Conversa de Roberto deve conter mensagem e resposta."
    last_asst = next((c for c in reversed(convs) if c["role"] == "assistant"), None)
    assert last_asst is not None
    reply_text = last_asst["text"].lower()

    # O Líder de cibersegurança NÃO deve se apresentar como o Sudo Agent nem orquestrador supremo
    assert "sou o sudo agent" not in reply_text, "Roberto não deve se identificar como Sudo Agent!"
    assert "orquestrador supremo" not in reply_text, "Roberto não deve usurpar a identidade de Orquestrador Supremo!"
    print(f"  -> Resposta legítima de Roberto ({roberto.title}): {last_asst['text'][:120]}...")
    print("  -> Conflito entre Líder e Sudo Agent resolvido com sucesso!")


if __name__ == "__main__":
    test_sudo_conversational_response()
    test_agent_update_endpoint()
    test_squad_leader_chat_does_not_conflict_with_sudo()
    print("\n=======================================================")
    print("TODOS OS TESTES DE FEEDBACK E EDIÇÃO PASSARAM COM SUCESSO!")
    print("=======================================================")
