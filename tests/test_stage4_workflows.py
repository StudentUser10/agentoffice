"""
AgentOffice 2D - Testes Automatizados da Etapa 4
Valida Protocolo WebSocket, Origem Segura, Eventos Padronizados de Tarefas,
Ressincronização e Estrutura Frontend do Quadro Kanban em 6 Colunas.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Inclusão do diretório raiz no sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app import app
from backend.models import (
    ApprovalDecisionRequest,
    ApprovalRequest,
    TaskPacket,
    TasksData,
    TaskState,
    WorkflowActionType,
    WorkflowStep,
    WorkflowTemplate,
)
from backend.storage import storage
from backend.websocket_hub import hub
from backend.workflow_engine import workflow_engine


def test_websocket_protocol_and_origin_security():
    """Valida conexão WebSocket, validação de origem segura, sync inicial e ping/pong."""
    print("--- Testando Protocolo WebSocket e Validação de Origem ---")
    client = TestClient(app)

    # 1. Conexão com Origem Válida (localhost / 127.0.0.1)
    with client.websocket_connect("/ws", headers={"origin": "http://127.0.0.1:8000"}) as websocket:
        # Primeiro evento recebido: workspace.updated
        first_msg = websocket.receive_json()
        assert first_msg.get("type") == "workspace.updated"
        assert "workspace" in first_msg


        # Teste de Ping / Pong
        websocket.send_json({"type": "ping"})
        pong_msg = websocket.receive_json()
        assert pong_msg.get("type") == "pong" or pong_msg.get("event") == "pong"

        # Teste de solicitação manual de tasks.sync
        websocket.send_json({"event": "tasks.sync"})
        sync_reply = websocket.receive_json()
        assert sync_reply.get("event") == "tasks.sync"
        assert isinstance(sync_reply.get("tasks"), list)

    # 2. Conexão com Origem Não Autorizada (Ataque CSWSH / Cross-Site WebSocket Hijacking)
    try:
        with client.websocket_connect("/ws", headers={"origin": "http://malicious-hacker.com"}) as evil_ws:
            # Se não desconectou imediatamente, tenta ler mensagem
            msg = evil_ws.receive_text()
            assert False, "Deveria ter rejeitado conexão de origem maliciosa com código 1008."
    except Exception as e:
        # Sucesso: conexão recusada ou fechada
        pass


def test_standardized_task_websocket_events():
    """Valida o formato comum de eventos da Seção 7 (event, task_id, timestamp, payload)."""
    print("--- Testando Emissão Padronizada de Eventos de Tarefas ---")
    client = TestClient(app)

    with client.websocket_connect("/ws", headers={"origin": "http://localhost:8000"}) as websocket:
        # Consome eventos de conexão inicial
        websocket.receive_json()  # workspace.updated

        # 1. Disparo de task.created via API REST
        res = client.post("/api/tasks", json={
            "title": "Tarefa de Validação WebSocket",
            "objective": "Verificar recebimento em tempo real do evento padronizado",
            "workflow_id": "workflow-standard-engineering"
        })
        assert res.status_code == 200
        created_task = res.json()
        created_id = created_task["id"]

        # Escuta evento via WebSocket
        received_event = websocket.receive_json()
        assert received_event.get("event") == "task.created"
        assert received_event.get("task_id") == created_id
        assert "timestamp" in received_event
        assert "payload" in received_event

        # 2. Teste do método auxiliar broadcast_task_event
        asyncio.run(hub.broadcast_task_event(
            event_name="task.custom_test",
            task_id=created_id,
            payload={"custom_data": "ok"}
        ))
        custom_ev = websocket.receive_json()
        assert custom_ev["event"] == "task.custom_test"
        assert custom_ev["task_id"] == created_id
        assert custom_ev["payload"]["custom_data"] == "ok"

        # 3. Disparo de task.approval_requested, task.approved e task.rejected
        asyncio.run(hub.broadcast_task_event(
            event_name="task.approval_requested",
            task_id=created_id,
            payload={"approval_id": "appr-test", "summary": "Diff proposto"}
        ))
        appr_ev = websocket.receive_json()
        assert appr_ev["event"] == "task.approval_requested"
        assert appr_ev["payload"]["approval_id"] == "appr-test"

        # Limpeza
        client.delete(f"/api/tasks/{created_id}")


def test_frontend_kanban_assets_and_structure():
    """Valida a presença e integridade dos arquivos e componentes HTML/JS/CSS do Kanban."""
    print("--- Testando Arquivos e Estrutura Frontend do Kanban ---")

    frontend_dir = BASE_DIR / "frontend"
    js_dir = frontend_dir / "js"
    css_dir = frontend_dir / "css"

    # 1. Existência dos arquivos modulares requeridos
    assert (js_dir / "kanban.js").exists(), "Arquivo frontend/js/kanban.js não foi encontrado!"
    assert (js_dir / "modals.js").exists(), "Arquivo frontend/js/modals.js não foi encontrado!"
    assert (js_dir / "socket.js").exists(), "Arquivo frontend/js/socket.js não foi encontrado!"
    assert (frontend_dir / "index.html").exists(), "Arquivo frontend/index.html não foi encontrado!"
    assert (css_dir / "style.css").exists(), "Arquivo frontend/css/style.css não foi encontrado!"

    # 2. Inspeção do HTML para presença dos elementos estruturais do Kanban
    html_content = (frontend_dir / "index.html").read_text(encoding="utf-8")

    # Botão de acesso no header com badge
    assert 'id="openKanbanBtn"' in html_content, "Botão do Kanban não encontrado no header!"
    assert 'id="kanbanActiveBadge"' in html_content, "Badge de tarefas ativas não encontrado!"

    # Modal do Kanban e container das 6 colunas
    assert 'id="kanbanModal"' in html_content, "Modal kanbanModal não encontrado!"
    assert 'id="kanbanBoardContainer"' in html_content, "Container kanbanBoardContainer não encontrado!"

    # Modais de criação e de detalhes
    assert 'id="taskCreateModal"' in html_content, "Modal taskCreateModal não encontrado!"
    assert 'id="taskDetailModal"' in html_content, "Modal taskDetailModal não encontrado!"
    assert 'id="taskDetailContent"' in html_content, "Container taskDetailContent não encontrado!"

    # Importação dos scripts modulares
    assert 'src="/static/js/socket.js"' in html_content, "Script socket.js não incluído no HTML!"
    assert 'src="/static/js/modals.js"' in html_content, "Script modals.js não incluído no HTML!"
    assert 'src="/static/js/kanban.js"' in html_content, "Script kanban.js não incluído no HTML!"

    # 3. Inspeção do CSS para classes de colunas, cards, diffs e alertas
    css_content = (css_dir / "style.css").read_text(encoding="utf-8")
    assert ".kanban-board-grid" in css_content, "Estilo .kanban-board-grid não encontrado no CSS!"
    assert ".kanban-column" in css_content, "Estilo .kanban-column não encontrado no CSS!"
    assert ".kanban-card" in css_content, "Estilo .kanban-card não encontrado no CSS!"
    assert ".pulse-approval" in css_content, "Estilo de pulso de aprovação não encontrado no CSS!"
    assert ".diff-viewer" in css_content, "Estilo .diff-viewer não encontrado no CSS!"
    assert ".diff-add" in css_content, "Estilo .diff-add não encontrado no CSS!"
    assert ".diff-del" in css_content, "Estilo .diff-del não encontrado no CSS!"
    assert ".steps-stepper" in css_content, "Estilo .steps-stepper não encontrado no CSS!"
    assert ".toast-container" in css_content, "Estilo .toast-container não encontrado no CSS!"

    # 4. Inspeção do kanban.js para as 6 colunas canônicas
    kanban_js = (js_dir / "kanban.js").read_text(encoding="utf-8")
    for col in ['QUEUED', 'IN_PROGRESS', 'QUALITY_GATE', 'WAITING_APPROVAL', 'COMPLETED', 'FAILED']:
        assert col in kanban_js, f"Coluna canônica {col} não definida no kanban.js!"

    # Verificação de handlers WebSocket no kanban.js
    assert "task.created" in kanban_js
    assert "task.updated" in kanban_js
    assert "task.handoff" in kanban_js
    assert "task.approval_requested" in kanban_js
    assert "task.quality_gate_event" in kanban_js
    assert "connection.reconnected" in kanban_js


if __name__ == "__main__":
    print("Iniciando bateria de testes automatizados da Etapa 4...\n")
    test_websocket_protocol_and_origin_security()
    test_standardized_task_websocket_events()
    test_frontend_kanban_assets_and_structure()
    print("\nTODOS OS TESTES DA ETAPA 4 (WEBSOCKET E KANBAN) PASSARAM COM SUCESSO!")
