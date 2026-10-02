"""
AgentOffice 2D - WebSocket Hub
Gerenciador centralizado de conexões e despacho de eventos em tempo real.
"""

import json
import logging
from typing import Set, Dict, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger("agentoffice.websocket")


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Cliente WebSocket conectado. Total ativos: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Cliente WebSocket desconectado. Total ativos: {len(self.active_connections)}")

    async def broadcast(self, data: Dict[str, Any]):
        """Envia mensagem serializada em JSON para todos os clientes conectados."""
        if not self.active_connections:
            return

        payload = json.dumps(data, ensure_ascii=False)
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning(f"Erro ao enviar para WebSocket: {e}")
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    # --- Métodos de Conveniência para o Protocolo de Eventos ---

    async def broadcast_agent_status(self, agent_id: str, state: str):
        """Notifica mudança no estado do agente (idle, thinking, working, walking, reporting)."""
        await self.broadcast({
            "type": "agent.status",
            "id": agent_id,
            "state": state
        })

    async def broadcast_agent_move(
        self,
        agent_id: str,
        target_x: int,
        target_y: int,
        action: str = "walk",
        speed: float = 2.0
    ):
        """Notifica movimentação física de um NPC para coordenadas específicas."""
        await self.broadcast({
            "type": "agent.move",
            "id": agent_id,
            "target_x": target_x,
            "target_y": target_y,
            "action": action,
            "speed": speed
        })

    async def broadcast_chat_delta(self, agent_id: str, delta: str):
        """Streaming de tokens em tempo real."""
        await self.broadcast({
            "type": "chat.delta",
            "agent_id": agent_id,
            "delta": delta
        })

    async def broadcast_system_notice(self, message: str):
        """Notificação de sistema (ex: atribuições, relatórios entregues)."""
        await self.broadcast({
            "type": "chat.system_notice",
            "message": message
        })

    async def broadcast_chat_completed(self, agent_id: str, message: str):
        """Notifica finalização de uma resposta completa de chat."""
        await self.broadcast({
            "type": "chat.completed",
            "agent_id": agent_id,
            "message": message
        })

    async def broadcast_chat_error(self, agent_id: str, error: str):
        """Notifica erro na execução do modelo."""
        await self.broadcast({
            "type": "chat.error",
            "agent_id": agent_id,
            "error": error
        })

    async def broadcast_workspace_updated(self, workspace_data: Dict[str, Any]):
        """Notifica atualização do layout do escritório ou cadastro de agentes."""
        await self.broadcast({
            "type": "workspace.updated",
            "workspace": workspace_data
        })

    async def broadcast_task_event(self, event_name: str, task_id: str, payload: Optional[Dict[str, Any]] = None):
        """Dispara eventos de tarefas padronizados conforme o protocolo da Etapa 4 (Section 7)."""
        import time
        await self.broadcast({
            "event": event_name,
            "type": event_name,
            "task_id": task_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": payload or {}
        })


# Instância global singleton
hub = ConnectionManager()
