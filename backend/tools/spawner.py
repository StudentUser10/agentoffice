"""
AgentOffice 2D - Dynamic Subagent Spawner (Etapa 6)
Lógica de validação de SpawnSubagentParams, alocação de mesa vaga no Canvas,
criação estruturada do subagente em memória/disco e disparo de eventos WebSocket.
"""

import logging
import uuid
from typing import Optional, Tuple

from backend.models import (
    Agent,
    AgentRoleType,
    AgentState,
    Desk,
    SpawnSubagentParams,
    WorkspaceData,
)
from backend.storage import storage
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.tools.spawner")


class DeskUnavailableError(Exception):
    """Exceção levantada quando todas as mesas do escritório estão ocupadas."""
    pass


class SpawnerError(Exception):
    """Exceção geral de criação/despawning de subagentes."""
    pass


async def spawn_subagent(
    supervisor_id: str,
    params: SpawnSubagentParams,
    workspace: Optional[WorkspaceData] = None
) -> Tuple[Agent, Desk]:
    """
    Cria e posiciona dinamicamente um subagente especializado em uma mesa vaga.
    Exige rigorosamente especificação do O Quê, Quando, Como e Condição de Término.
    """
    if workspace is None:
        workspace = storage.load_workspace()

    # 1. Localizar o Supervisor
    supervisor = next((a for a in workspace.agents if a.id == supervisor_id), None)
    if not supervisor:
        raise SpawnerError(f"Supervisor '{supervisor_id}' não encontrado no escritório.")

    # 2. Localizar a primeira mesa livre
    free_desk = next((d for d in workspace.desks if not d.agent_id), None)
    if not free_desk:
        raise DeskUnavailableError(
            "Todas as mesas do escritório estão ocupadas no momento. "
            "Não foi possível alocar o subagente. Libere uma mesa para prosseguir."
        )

    # 3. Montar o Prompt do Subagente estruturado a partir do contrato cirúrgico
    tools_list_str = ", ".join(params.allowed_tools) if params.allowed_tools else "fs_read_file, fs_write_file"
    system_prompt = (
        f"Você é {params.name}, {params.role_title} no AgentOffice 2D.\n"
        f"Seu Tech Lead e Supervisor direto é {supervisor.name}.\n\n"
        f"=== CONTRATO CIRÚRGICO DE DELEGAÇÃO ===\n\n"
        f"🎯 [O QUÊ ENTREGAR - ESCOPO EXATO]:\n{params.what_exact_task}\n\n"
        f"⛔ [FORA DE ESCOPO / ESTRITAMENTE PROIBIDO]:\n{params.what_out_of_scope}\n\n"
        f"⏳ [QUANDO EXECUTAR E DEPENDÊNCIAS]:\n{params.when_triggers}\n\n"
        f"🛠️ [COMO EXECUTAR / METODOLOGIA E REGRAS TÉCNICAS]:\n{params.how_instructions}\n\n"
        f"🏁 [CONDIÇÃO DE CONCLUSÃO (EXIT CONDITION)]:\n{params.exit_condition}\n\n"
        f"🔧 [FERRAMENTAS AUTORIZADAS]: {tools_list_str}\n\n"
        "INSTRUÇÕES DE EXECUÇÃO:\n"
        "- Você opera dentro do workspace sandbox seguro. Utilize as ferramentas de arquivos quando necessário.\n"
        "- Para gravar arquivos, chame a ferramenta fs_write_file.\n"
        "- Para criar diretórios, chame fs_create_directory.\n"
        "- Para inspecionar ou ler arquivos existentes, chame fs_read_file e fs_list_directory.\n"
        "- Seja extremamente técnico, objetivo e preciso. Cumpra rigorosamente a condição de conclusão."
    )

    agent_id = f"agent-{uuid.uuid4().hex[:6]}"
    
    # 4. Instanciar novo Agente
    new_agent = Agent(
        id=agent_id,
        name=params.name.strip(),
        title=params.role_title.strip(),
        avatar_id=params.avatar_id or "avatar_1",
        role_type=AgentRoleType.WORKER,
        supervisor_id=supervisor.id,
        subordinate_ids=[],
        desk_id=free_desk.id,
        system_prompt=system_prompt,
        model_name=(params.model_override or "").strip(),
        state=AgentState.IDLE,
        mission=params,
        is_temporary=True
    )

    # 5. Ocupar a mesa e vincular ao Supervisor
    free_desk.agent_id = agent_id
    if agent_id not in supervisor.subordinate_ids:
        supervisor.subordinate_ids.append(agent_id)

    workspace.agents.append(new_agent)
    storage.save_workspace(workspace)

    # 6. Disparar Eventos em Tempo Real via WebSocket
    await hub.broadcast_agent_spawned({
        "id": new_agent.id,
        "name": new_agent.name,
        "title": new_agent.title,
        "avatar_id": new_agent.avatar_id,
        "role_type": new_agent.role_type.value,
        "supervisor_id": new_agent.supervisor_id,
        "desk_id": free_desk.id,
        "seat_x": free_desk.seat_x,
        "seat_y": free_desk.seat_y,
        "mission": params.model_dump(),
        "is_temporary": True
    })

    await hub.broadcast_workspace_updated(workspace.model_dump())
    await hub.broadcast_system_notice(
        f"✨ {supervisor.name} contratou '{new_agent.name}' ({new_agent.title}) para a {free_desk.name}!"
    )

    logger.info(
        f"Subagente '{new_agent.name}' ({agent_id}) criado com sucesso na mesa '{free_desk.id}' "
        f"sob comando de '{supervisor.name}'."
    )

    return new_agent, free_desk


async def despawn_subagent(
    agent_id: str,
    workspace: Optional[WorkspaceData] = None
) -> bool:
    """
    Libera a mesa e encerra o ciclo de vida de um subagente temporário.
    """
    if workspace is None:
        workspace = storage.load_workspace()

    agent = next((a for a in workspace.agents if a.id == agent_id), None)
    if not agent:
        return False

    desk = next((d for d in workspace.desks if d.agent_id == agent_id), None)
    if desk:
        desk.agent_id = None

    # Remover da lista de subordinados do supervisor
    if agent.supervisor_id:
        sup = next((a for a in workspace.agents if a.id == agent.supervisor_id), None)
        if sup and agent_id in sup.subordinate_ids:
            sup.subordinate_ids.remove(agent_id)

    # Remover do workspace
    workspace.agents = [a for a in workspace.agents if a.id != agent_id]
    storage.save_workspace(workspace)

    # Notificar clientes WebSocket
    if desk:
        await hub.broadcast_agent_despawned(agent_id, desk.id)
    await hub.broadcast_workspace_updated(workspace.model_dump())
    await hub.broadcast_system_notice(
        f"🚪 Subagente '{agent.name}' concluiu suas tarefas e liberou a {desk.name if desk else 'mesa'}."
    )

    return True
