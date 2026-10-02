"""
Testes Automatizados - Claude Skills Hub & Execution Engine (AgentOffice 2D)
Valida:
1. Inicialização e listagem de Claude Skills e Catálogo Oficial.
2. Autoridade do Sudo Agent Pax (@aiox-master) e permissões de subordinados.
3. Instalação de skills (catálogo, customizada e via URL mock).
4. Atribuição de skills para squads e agentes individuais.
5. Injeção dinâmica de contexto de skills no system prompt.
6. Recomendação e concessão autônoma de skills com base no épico.
7. Endpoints REST (/api/skills).
8. Comandos de chat (*skills, *skill-install, *skill-assign).
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Any

from fastapi.testclient import TestClient

# Assegurar path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app import app
from backend.models import Agent, AgentTier, ClaudeSkill, SkillInstallRequest, Squad, WorkspaceData
from backend.storage import storage
from backend.tools.skill_manager import skill_manager
from backend.orchestrator_multi_tier import multi_tier_orchestrator
from backend.orchestrator import orchestrator

client = TestClient(app)


def test_skills_catalog_and_installed():
    print("\n--- Testando Catálogo e Skills Instaladas ---")
    installed = skill_manager.list_installed_skills()
    assert len(installed) >= 5, f"Deveria haver pelo menos 5 skills instaladas, encontrado: {len(installed)}"
    
    catalog = skill_manager.list_catalog()
    assert len(catalog) >= 7, f"Catálogo deveria conter 7 skills, encontrado: {len(catalog)}"
    
    skill_ids = [s.id for s in installed]
    print(f"  -> Skills instaladas: {skill_ids}")
    assert "frontend-craftsman" in skill_ids
    assert "claude-code-architect" in skill_ids
    assert "python-security-auditor" in skill_ids
    print("  -> Catálogo e persistência validados com sucesso!")


def test_agent_permissions_and_authority():
    print("\n--- Testando Autoridade de Pax e Permissões de Subordinados ---")
    
    pax = Agent(
        id="agent-sudo",
        name="Pax (@aiox-master)",
        title="Diretor Geral",
        tier=AgentTier.SUDO,
        desk_id="desk-sudo",
        room_id="room_sudo",
        aiox_role="master"
    )
    
    dex = Agent(
        id="agent-9debfa",
        name="Dex (@dev)",
        title="Senior Software Engineer",
        tier=AgentTier.WORKER,
        desk_id="desk-3",
        room_id="room_dev",
        squad_id="squad-core-engineering",
        aiox_role="dev"
    )

    skill_frontend = skill_manager.get_skill("frontend-craftsman")
    assert skill_frontend is not None

    # Pax SEMPRE tem autoridade irrestrita para qualquer skill
    assert skill_manager.can_agent_use_skill(pax, skill_frontend) is True
    print("  -> Pax (@aiox-master) possui autoridade total confirmada!")

    # Dex possui papel 'dev', que está em allowed_roles de frontend-craftsman
    assert skill_manager.can_agent_use_skill(dex, skill_frontend) is True
    print("  -> Dex (@dev) autorizado para frontend-craftsman via role 'dev'!")


def test_skill_prompt_injection():
    print("\n--- Testando Injeção Dinâmica de Claude Skills no Prompt ---")
    
    dex = Agent(
        id="agent-9debfa",
        name="Dex (@dev)",
        title="Senior Software Engineer",
        tier=AgentTier.WORKER,
        desk_id="desk-3",
        room_id="room_dev",
        squad_id="squad-core-engineering",
        aiox_role="dev"
    )

    base_prompt = "Você é o desenvolvedor responsável pela entrega."
    injected_prompt = skill_manager.inject_skills_into_prompt(dex, base_prompt)

    assert "⚡ [CLAUDE SKILLS ATIVADAS PARA SUA EXECUÇÃO]" in injected_prompt
    assert "Claude Frontend Craftsman" in injected_prompt or "Claude System Architect" in injected_prompt
    print("  -> Injeção de instruções de Claude Skills no prompt validada com sucesso!")


def test_skill_installation_and_assignment():
    print("\n--- Testando Instalação e Atribuição de Nova Skill ---")
    
    # 1. Instalar skill customizada
    req = SkillInstallRequest(
        skill_id="docker-devops-ninja",
        name="Docker & Container DevOps Ninja",
        description="Especialista em Dockerfile multi-stage, docker-compose e otimização de imagens.",
        category="devops",
        tags=["docker", "containers", "devops"],
        instructions="DIRETRIZES: Use multi-stage builds, non-root users e reduza camadas desnecessárias.",
        assigned_to=["squad-core-engineering"]
    )
    
    skill = asyncio.run(skill_manager.download_or_install_skill(req, requester_agent_id="test-runner"))
    assert skill.id == "docker-devops-ninja"
    assert skill.name == "Docker & Container DevOps Ninja"
    print(f"  -> Skill '{skill.id}' instalada com sucesso!")

    # 2. Atribuir a um agente específico
    updated_skill = asyncio.run(skill_manager.assign_skill("docker-devops-ninja", "agent-1c137c", "assign"))
    assert "agent-1c137c" in updated_skill.assigned_to
    print("  -> Atribuição para 'agent-1c137c' realizada com sucesso!")

    # 3. Remover skill de teste
    removed = asyncio.run(skill_manager.remove_skill("docker-devops-ninja"))
    assert removed is True
    assert skill_manager.get_skill("docker-devops-ninja") is None
    print("  -> Remoção da skill de teste validada com sucesso!")


def test_auto_recommend_and_grant_skills():
    print("\n--- Testando Recomendação Autônoma de Skills pelo Sudo Agent Pax ---")
    
    aria = Agent(
        id="agent-1c137c",
        name="Aria (@architect)",
        title="Software Architect",
        tier=AgentTier.SQUAD_LEADER,
        desk_id="desk-1",
        room_id="room_dev",
        squad_id="squad-core-engineering",
        aiox_role="architect"
    )
    squad = Squad(
        id="squad-core-engineering",
        name="Squad Core Engineering",
        room_id="room_dev",
        leader_id="agent-1c137c"
    )

    # Simular demanda de frontend
    granted = asyncio.run(skill_manager.auto_recommend_and_grant_skills(
        user_prompt="Crie um site showcase bonito em HTML e CSS para o AgentOffice 2D",
        epic_title="Desenvolvimento do Site Showcase",
        leader=aria,
        squad=squad
    ))

    granted_ids = [s.id for s in granted]
    print(f"  -> Skills concedidas por Pax para site showcase: {granted_ids}")
    assert "frontend-craftsman" in granted_ids
    print("  -> Recomendação autônoma de frontend-craftsman aprovada!")


def test_skills_rest_endpoints():
    print("\n--- Testando Endpoints REST /api/skills ---")
    
    # 1. GET /api/skills
    res = client.get("/api/skills")
    assert res.status_code == 200
    data = res.json()
    assert "installed" in data
    assert "catalog" in data
    assert data["total_installed"] >= 5
    print(f"  -> GET /api/skills retornou {data['total_installed']} skills instaladas!")

    # 2. POST /api/skills/install
    install_payload = {
        "skill_id": "test-rest-skill",
        "name": "REST Test Skill",
        "description": "Skill para validar a API REST.",
        "instructions": "Diretrizes de teste REST.",
        "category": "qa"
    }
    res_inst = client.post("/api/skills/install", json=install_payload)
    assert res_inst.status_code == 200
    inst_data = res_inst.json()
    assert inst_data["status"] == "installed"
    assert inst_data["skill"]["id"] == "test-rest-skill"
    print("  -> POST /api/skills/install validado!")

    # 3. GET /api/skills/test-rest-skill
    res_get = client.get("/api/skills/test-rest-skill")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == "test-rest-skill"

    # 4. POST /api/skills/assign
    res_assign = client.post("/api/skills/assign", json={
        "skill_id": "test-rest-skill",
        "target_id": "squad-security",
        "action": "assign"
    })
    assert res_assign.status_code == 200
    assert "squad-security" in res_assign.json()["skill"]["assigned_to"]
    print("  -> POST /api/skills/assign validado!")

    # 5. DELETE /api/skills/test-rest-skill
    res_del = client.delete("/api/skills/test-rest-skill")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "removed"
    print("  -> DELETE /api/skills/{id} validado!")


def test_skills_chat_commands():
    print("\n--- Testando Comandos de Chat de Skills ---")
    
    # 1. Executar *skills no Sudo Agent Pax
    res_skills = asyncio.run(multi_tier_orchestrator.handle_sudo_macro_goal("*skills"))
    reply = res_skills.get("reply", "")
    assert "Central de Claude Skills" in reply
    assert "frontend-craftsman" in reply
    print("  -> Chat command *skills executado com sucesso no Sudo Agent!")

    # 2. Executar *skill-install no Sudo Agent Pax
    res_inst = asyncio.run(multi_tier_orchestrator.handle_sudo_macro_goal("*skill-install scraping-data-extractor"))
    install_reply = res_inst.get("reply", "")
    assert "instalada com sucesso" in install_reply or "scraping-data-extractor" in install_reply
    print("  -> Chat command *skill-install validado com sucesso!")

    # 3. Executar *skills no Líder de Squad Aria
    alex_id = "agent-1c137c"
    asyncio.run(orchestrator.execute_task(alex_id, "*skills"))
    ws = storage.load_workspace()
    squad_reply = ws.conversations[alex_id][-1]["text"]
    assert "Central de Claude Skills" in squad_reply
    print("  -> Chat command *skills no líder departamental validado com sucesso!")


if __name__ == "__main__":
    print("=======================================================")
    print("INICIANDO SUÍTE DE TESTES: CLAUDE SKILLS HUB")
    print("=======================================================")
    test_skills_catalog_and_installed()
    test_agent_permissions_and_authority()
    test_skill_prompt_injection()
    test_skill_installation_and_assignment()
    test_auto_recommend_and_grant_skills()
    test_skills_rest_endpoints()
    test_skills_chat_commands()
    print("\n=======================================================")
    print("TODOS OS TESTES DE CLAUDE SKILLS PASSARAM COM 100% SUCESSO!")
    print("=======================================================")
