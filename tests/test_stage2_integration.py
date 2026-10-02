"""
Teste de integração ponta a ponta da Etapa 2
Valida conexão WebSocket, contratação com hierarquia e envio de tarefa ao supervisor.
"""

import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app import app
from backend.storage import storage


def test_full_agent_workflow():
    client = TestClient(app)

    # 1. Reset limpo do workspace
    ws = storage.load_workspace()
    ws.agents = []
    for d in ws.desks:
        d.agent_id = None
    storage.save_workspace(ws)

    # 2. Conectar cliente WebSocket
    with client.websocket_connect("/ws") as websocket:
        # Receber estado inicial do workspace
        init_msg = websocket.receive_json()
        assert init_msg["type"] == "workspace.updated"

        # 3. Criar Supervisor na Mesa 1
        sup_res = client.post("/api/agents", json={
            "name": "Alex Tech Lead",
            "title": "Tech Lead",
            "role_type": "supervisor",
            "desk_id": "desk-1",
            "system_prompt": "Você é o Tech Lead do time."
        })
        assert sup_res.status_code == 200
        sup = sup_res.json()
        sup_id = sup["id"]

        # WebSocket deve receber atualização do workspace e aviso de sistema
        event_ws = websocket.receive_json()
        assert event_ws["type"] == "workspace.updated"
        event_notice = websocket.receive_json()
        assert event_notice["type"] == "chat.system_notice"
        assert "Alex Tech Lead" in event_notice["message"]

        # 4. Criar Worker na Mesa 2 subordinado ao Supervisor
        worker_res = client.post("/api/agents", json={
            "name": "Beatriz Backend",
            "title": "Backend Dev",
            "role_type": "worker",
            "supervisor_id": sup_id,
            "desk_id": "desk-2",
            "system_prompt": "Você desenvolve APIs robustas."
        })
        assert worker_res.status_code == 200
        worker = worker_res.json()
        worker_id = worker["id"]

        # WebSocket recebe atualizações
        websocket.receive_json() # workspace.updated
        websocket.receive_json() # chat.system_notice

        # 5. Enviar mensagem de chat para o Supervisor
        chat_res = client.post("/api/chat", json={
            "agent_id": sup_id,
            "message": "Construa uma rota para listar produtos."
        })
        assert chat_res.status_code == 200
        assert chat_res.json()["status"] == "started"

        # 6. Histórico de conversas
        conv_res = client.get(f"/api/agents/{sup_id}/conversations")
        assert conv_res.status_code == 200
        convs = conv_res.json()
        assert len(convs) >= 1
        assert convs[0]["text"] == "Construa uma rota para listar produtos."

    print("Teste de integração ponta a ponta concluído com 100% de sucesso!")


if __name__ == "__main__":
    test_full_agent_workflow()
