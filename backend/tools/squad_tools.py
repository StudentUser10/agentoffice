"""
AgentOffice 2D - Squad Tools & Inter-Squad Communication (Etapa 7: Arquitetura Multinível)
Implementa as ferramentas:
1. dispatch_to_squad: Sudo Agent despacha épicos com critérios de aceite para líderes de squad.
2. request_cross_squad_help: Líderes solicitam assistência técnica lateral a outros squads.
3. resolve_cross_squad_ticket: Conclui e entrega artefatos de assistência técnica inter-squad.
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from backend.models import (
    Agent,
    AgentTier,
    CrossSquadTicket,
    DispatchToSquadParams,
    RequestCrossSquadParams,
    Squad,
    WorkspaceData,
)
from backend.storage import storage
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.tools.squad_tools")


class SquadNotFoundError(Exception):
    """Exceção levantada quando um Squad requisitado não existe."""
    pass


class LeaderNotFoundError(Exception):
    """Exceção levantada quando o líder de squad não é localizado."""
    pass


def _get_squad_by_id(squad_id: str) -> Optional[Squad]:
    """Busca squad no arquivo squads.json ou cria fallback dos squads conhecidos."""
    squads_data = storage.load_squads()
    for s in squads_data.squads:
        if s.id == squad_id or s.name.lower() == squad_id.lower():
            return s
    return None


async def dispatch_to_squad(
    target_squad_id: str,
    epic_title: str,
    objective: str,
    acceptance_criteria: str,
    sudo_agent_id: Optional[str] = None,
    workspace: Optional[WorkspaceData] = None
) -> str:
    """
    Ferramenta exclusiva do Sudo Agent para despachar metas macro a Líderes de Squad.
    """
    if workspace is None:
        workspace = storage.load_workspace()

    squad = _get_squad_by_id(target_squad_id)
    squad_name = squad.name if squad else target_squad_id
    room_id = squad.room_id if squad else "room_dev"
    leader_id = squad.leader_id if squad else ""

    # Se não temos leader_id no squad, procurar no workspace o líder daquela sala/squad
    if not leader_id:
        leader_agent = next(
            (a for a in workspace.agents if (a.squad_id == target_squad_id or a.room_id == room_id) and a.tier == AgentTier.SQUAD_LEADER),
            None
        )
        if leader_agent:
            leader_id = leader_agent.id

    logger.info(
        f"[Sudo Dispatch] Épico '{epic_title}' despachado para squad '{target_squad_id}' "
        f"(Líder: {leader_id}, Sala: {room_id})"
    )

    # 1. Disparar evento WebSocket squad.dispatched para renderização no mapa e HUD
    await hub.broadcast_squad_dispatched({
        "squad_id": target_squad_id,
        "squad_name": squad_name,
        "room_id": room_id,
        "leader_id": leader_id,
        "epic_title": epic_title,
        "objective": objective,
        "acceptance_criteria": acceptance_criteria,
        "sudo_agent_id": sudo_agent_id
    })

    # 2. Registrar no console de eventos
    await hub.broadcast_system_notice(
        f"👑 [Sudo Agent] Épico '{epic_title}' despachado para o squad '{squad_name}'!"
    )

    return (
        f"Épico '{epic_title}' despachado com sucesso para o squad '{squad_name}' "
        f"(Sala: {room_id}). O Líder Departamental coordenará a execução."
    )


async def request_cross_squad_help(
    requesting_leader_id: str,
    target_squad_id: str,
    reason_why_needed: str,
    what_exact_service: str,
    how_format_response: str,
    workspace: Optional[WorkspaceData] = None
) -> Tuple[CrossSquadTicket, str]:
    """
    Ferramenta de comunicação lateral: um Líder de Squad solicita assistência técnica
    a outro departamento, gerando um ticket auditável e trânsito físico no mapa 2D.
    """
    if workspace is None:
        workspace = storage.load_workspace()

    req_leader = next((a for a in workspace.agents if a.id == requesting_leader_id), None)
    if not req_leader:
        raise LeaderNotFoundError(f"Líder solicitante '{requesting_leader_id}' não encontrado no escritório.")

    target_squad = _get_squad_by_id(target_squad_id)
    target_room_id = target_squad.room_id if target_squad else "room_sec"
    target_squad_name = target_squad.name if target_squad else target_squad_id

    # Identificar o líder de destino
    target_leader = next(
        (a for a in workspace.agents if (a.squad_id == target_squad_id or a.room_id == target_room_id) and a.tier == AgentTier.SQUAD_LEADER),
        None
    )
    if not target_leader:
        # Fallback: qualquer agente na sala de destino
        target_leader = next((a for a in workspace.agents if a.room_id == target_room_id), None)

    target_leader_id = target_leader.id if target_leader else "unknown_leader"
    target_desk_id = target_leader.desk_id if target_leader else "desk-sec-1"

    # Criar o ticket formal de cooperação inter-squad
    ticket = CrossSquadTicket(
        from_squad_id=req_leader.squad_id or req_leader.room_id,
        to_squad_id=target_squad_id,
        requesting_leader_id=requesting_leader_id,
        reason_out_of_scope=reason_why_needed,
        exact_requirement=what_exact_service,
        status="pending"
    )

    # Persistir ticket no workspace
    if not hasattr(workspace, "active_tickets") or workspace.active_tickets is None:
        workspace.active_tickets = []

    workspace.active_tickets.append(ticket)
    storage.save_workspace(workspace, backup=False)

    logger.info(
        f"[Cross-Squad] Ticket {ticket.ticket_id} criado de {req_leader.name} para {target_squad_name}: "
        f"{what_exact_service[:50]}"
    )

    # 1. Notificar criação do ticket (squad.cross_request)
    await hub.broadcast_squad_cross_request(
        ticket_data=ticket.model_dump(),
        from_leader_id=requesting_leader_id,
        to_leader_id=target_leader_id
    )

    # 2. Despachar trânsito físico pelo corredor (agent.cross_room_move)
    await hub.broadcast_agent_cross_room_move(
        agent_id=requesting_leader_id,
        from_room_id=req_leader.room_id,
        to_room_id=target_room_id,
        target_desk_id=target_desk_id,
        ticket_id=ticket.ticket_id,
        service_label=what_exact_service[:32]
    )

    # 3. Notificação no feed
    await hub.broadcast_system_notice(
        f"🤝 [Inter-Squad] {req_leader.name} solicitou assistência a {target_squad_name}: '{what_exact_service[:50]}...'"
    )

    msg = (
        f"Ticket Inter-Squad '{ticket.ticket_id[:8]}' aberto com sucesso para {target_squad_name}.\n"
        f"O Líder {req_leader.name} se deslocou até a {target_room_id} para apresentar a demanda."
    )
    return ticket, msg


async def resolve_cross_squad_ticket(
    ticket_id: str,
    result_artifact: str,
    workspace: Optional[WorkspaceData] = None
) -> bool:
    """
    Marca um ticket inter-squad como concluído e entrega o artefato resultante ao solicitante.
    """
    if workspace is None:
        workspace = storage.load_workspace()

    if not hasattr(workspace, "active_tickets") or not workspace.active_tickets:
        return False

    ticket = next((t for t in workspace.active_tickets if t.ticket_id == ticket_id), None)
    if not ticket:
        return False

    ticket.status = "delivered"
    ticket.result_artifact = result_artifact
    ticket.updated_at = time.time()
    storage.save_workspace(workspace, backup=False)

    # 1. Notificar resolução via WebSocket
    await hub.broadcast_squad_ticket_resolved(ticket.model_dump())

    # 2. Notificar no feed
    await hub.broadcast_system_notice(
        f"✅ [Inter-Squad] Ticket {ticket_id[:8]} foi resolvido e o parecer técnico foi entregue ao solicitante!"
    )

    return True


def list_active_tickets(workspace: Optional[WorkspaceData] = None) -> List[CrossSquadTicket]:
    """Retorna a lista de tickets inter-squad vigentes."""
    if workspace is None:
        workspace = storage.load_workspace()
    return getattr(workspace, "active_tickets", []) or []
