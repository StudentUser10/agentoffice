"""
Teste automatizado para o Sudo Agent comandando os squads departamentais.
Valida:
1. Avaliação de prontidão: PURE_GREETING, ASK_CLARIFICATION e EXECUTE_SQUADS.
2. Rastreamento de esclarecimentos pendentes (_pending_clarifications).
3. Resposta do usuário desbloqueando execução imediata dos squads.
4. Confirmações ('pode começar', 'ok', 'bora') acionando os squads a partir do histórico.
5. Resolução cirúrgica da pasta em public/ (ex: agentoffice-showoff).
6. Execução completa de meta com despacho e entregas pelos squads.
"""

import asyncio
import os
import sys
from pathlib import Path

# Ajustar PYTHONPATH e encoding de stdout
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.orchestrator_multi_tier import multi_tier_orchestrator
from backend.storage import storage
from backend.models import Agent, AgentTier, Squad


async def test_sudo_evaluation_flow():
    print("\n--- [TEST 1] Avaliação de Prontidão e Intenção ---")
    ws = storage.load_workspace()
    sudo_agent = next((a for a in ws.agents if a.tier == AgentTier.SUDO), ws.agents[0])
    squads_data = storage.load_squads()
    available_squads = squads_data.squads or []

    # 1.1 Saudação pura
    res_greeting = await multi_tier_orchestrator._evaluate_sudo_goal_readiness(
        sudo_agent=sudo_agent,
        available_squads=available_squads,
        workspace=ws,
        user_prompt="olá, bom dia"
    )
    print(f"[*] 'olá, bom dia' -> action: {res_greeting['action']}")
    assert res_greeting["action"] == "PURE_GREETING", f"Esperado PURE_GREETING, obtido {res_greeting['action']}"

    # 1.2 Pergunta vaga -> ASK_CLARIFICATION
    res_vague = await multi_tier_orchestrator._evaluate_sudo_goal_readiness(
        sudo_agent=sudo_agent,
        available_squads=available_squads,
        workspace=ws,
        user_prompt="tenho uma ideia para fazer algo"
    )
    print(f"[*] 'tenho uma ideia...' -> action: {res_vague['action']}")
    assert res_vague["action"] == "ASK_CLARIFICATION", f"Esperado ASK_CLARIFICATION, obtido {res_vague['action']}"
    assert sudo_agent.id in multi_tier_orchestrator._pending_clarifications, "Deveria ter salvo esclarecimento pendente"

    # 1.3 Usuário responde ao esclarecimento -> EXECUTE_SQUADS imediato!
    res_answer = await multi_tier_orchestrator._evaluate_sudo_goal_readiness(
        sudo_agent=sudo_agent,
        available_squads=available_squads,
        workspace=ws,
        user_prompt="visual mais atraente e minimalista em dark mode"
    )
    print(f"[*] Resposta ao esclarecimento -> action: {res_answer['action']}")
    assert res_answer["action"] == "EXECUTE_SQUADS", f"Esperado EXECUTE_SQUADS, obtido {res_answer['action']}"
    assert "visual mais atraente e minimalista" in res_answer["consolidated_goal"]
    assert sudo_agent.id not in multi_tier_orchestrator._pending_clarifications, "Pending clarification deve ter sido consumido"
    print(f"   ↳ Meta consolidada: '{res_answer['consolidated_goal']}'")

    # 1.4 Usuário dá comando direto: 'melhore o showoff criado anteriormente' -> EXECUTE_SQUADS imediato!
    res_direct = await multi_tier_orchestrator._evaluate_sudo_goal_readiness(
        sudo_agent=sudo_agent,
        available_squads=available_squads,
        workspace=ws,
        user_prompt="melhore o showoff criado anteriormente"
    )
    print(f"[*] 'melhore o showoff...' -> action: {res_direct['action']}")
    assert res_direct["action"] == "EXECUTE_SQUADS", f"Esperado EXECUTE_SQUADS, obtido {res_direct['action']}"
    assert "showoff" in res_direct["consolidated_goal"]

    # 1.5 Usuário diz apenas 'pode começar' -> Recupera histórico e aciona squads!
    # Simular histórico com uma meta prévia
    ws.conversations[sudo_agent.id] = [
        {"role": "user", "text": "melhore o showoff criado anteriormente", "timestamp": 123},
        {"role": "assistant", "text": "Entendido! Como deseja aprimorar?", "timestamp": 124},
        {"role": "user", "text": "visual mais atraente e minimalista", "timestamp": 125}
    ]
    res_confirm = await multi_tier_orchestrator._evaluate_sudo_goal_readiness(
        sudo_agent=sudo_agent,
        available_squads=available_squads,
        workspace=ws,
        user_prompt="ok, pode ser, pode começar"
    )
    print(f"[*] 'ok, pode ser, pode começar' -> action: {res_confirm['action']}")
    assert res_confirm["action"] == "EXECUTE_SQUADS", f"Esperado EXECUTE_SQUADS, obtido {res_confirm['action']}"
    print(f"   ↳ Meta resgatada do histórico: '{res_confirm['consolidated_goal']}'")
    print("✅ [TEST 1] Passou com sucesso!")


async def test_folder_resolution():
    print("\n--- [TEST 2] Resolução Cirúrgica de Pastas em public/ ---")
    folder_showoff = multi_tier_orchestrator._resolve_target_project_folder(
        user_prompt="melhore o showoff criado anteriormente",
        epic_title="Modernização do Frontend"
    )
    print(f"[*] Showoff prompt -> Pasta resolvida: '{folder_showoff}'")
    assert folder_showoff == "agentoffice-showoff", f"Esperado 'agentoffice-showoff', obtido '{folder_showoff}'"

    folder_game = multi_tier_orchestrator._resolve_target_project_folder(
        user_prompt="crie um jogo arcade retrô",
        epic_title="Módulo de Jogo"
    )
    print(f"[*] Game prompt -> Pasta resolvida: '{folder_game}'")
    assert folder_game == "arcade-game", f"Esperado 'arcade-game', obtido '{folder_game}'"

    folder_todo = multi_tier_orchestrator._resolve_target_project_folder(
        user_prompt="faça um aplicativo de tarefas",
        epic_title="Gerenciador de Tarefas"
    )
    print(f"[*] Task prompt -> Pasta resolvida: '{folder_todo}'")
    assert folder_todo == "todo-app", f"Esperado 'todo-app', obtido '{folder_todo}'"
    print("✅ [TEST 2] Passou com sucesso!")


async def test_full_execution_flow():
    print("\n--- [TEST 3] Execução Completa: Sudo Agent Comandando os Squads ---")
    ws = storage.load_workspace()
    
    goal = "melhore o showoff criado anteriormente com visual atraente e minimalista"
    result = await multi_tier_orchestrator.handle_sudo_macro_goal(goal, workspace=ws)
    
    print(f"[*] Resultado da execução:")
    print(f"   ↳ Status: {result.get('status')}")
    print(f"   ↳ Sudo Agent: {result.get('sudo_agent')}")
    print(f"   ↳ Épicos despachados: {len(result.get('dispatches', []))}")
    print(f"   ↳ Entregas de squads: {len(result.get('squad_deliveries', []))}")

    assert result.get("status") == "success"
    assert len(result.get("dispatches", [])) >= 1, "Pelo menos um épico deve ter sido despachado"
    assert len(result.get("squad_deliveries", [])) >= 1, "Pelo menos uma entrega de squad deve ter sido concluída"

    # Verificar que os arquivos no showoff foram criados/atualizados
    showoff_html = Path(__file__).resolve().parent.parent / "workspace" / "public" / "agentoffice-showoff" / "index.html"
    showoff_css = Path(__file__).resolve().parent.parent / "workspace" / "public" / "agentoffice-showoff" / "style.css"
    showoff_js = Path(__file__).resolve().parent.parent / "workspace" / "public" / "agentoffice-showoff" / "app.js"

    assert showoff_html.exists(), "index.html deve existir em public/agentoffice-showoff"
    assert showoff_css.exists(), "style.css deve existir em public/agentoffice-showoff"
    assert showoff_js.exists(), "app.js deve existir em public/agentoffice-showoff"
    
    html_content = showoff_html.read_text(encoding="utf-8")
    print(f"[*] Verificado index.html ({len(html_content)} bytes)")
    assert "AgentOffice" in html_content

    print("✅ [TEST 3] Sudo Agent comandou os squads e entregou com sucesso!")


async def main():
    await test_sudo_evaluation_flow()
    await test_folder_resolution()
    await test_full_execution_flow()
    print("\n🎉 TODOS OS TESTES PASSARAM COM 100% DE SUCESSO!")


if __name__ == "__main__":
    asyncio.run(main())
