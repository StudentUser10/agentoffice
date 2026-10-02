"""
Testes automatizados da Etapa 2 (API e Máquina de Estados do Workflow Engine)
Verifica CRUD de squads, templates, workflows e tarefas via API REST,
transições de estado válidas e ilegais, controle de concorrência, timeouts e isolamento de falhas.
"""

import sys
import json
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app import app
from backend.models import (
    TaskPacket,
    TaskState,
    WorkflowStep,
    WorkflowActionType,
)
from backend.storage import storage
from backend.workflow_engine import (
    workflow_engine,
    InvalidTransitionError,
    TaskAlreadyRunningError,
)


def test_agent_templates_and_squads_crud():
    client = TestClient(app)

    # 1. Listar templates da biblioteca
    res = client.get("/api/agent-templates")
    assert res.status_code == 200
    templates = res.json()
    assert len(templates) >= 5
    tmpl_ids = [t["id"] for t in templates]
    assert "template-tech-lead" in tmpl_ids
    assert "template-python-dev" in tmpl_ids
    assert "template-qa" in tmpl_ids

    # 2. Listar squads iniciais
    res = client.get("/api/squads")
    assert res.status_code == 200
    squads = res.json()
    assert len(squads) >= 1
    assert squads[0]["name"] == "Squad Core Engineering"

    # 3. Criar novo Squad
    create_payload = {
        "name": "Squad Frontend & Design",
        "description": "Focado em interfaces e experiência de usuário",
        "agent_ids": ["template-writer", "template-analyst"]
    }
    res = client.post("/api/squads", json=create_payload)
    assert res.status_code == 200
    new_squad = res.json()
    assert new_squad["name"] == "Squad Frontend & Design"
    squad_id = new_squad["id"]

    # 4. Obter squad por ID
    res = client.get(f"/api/squads/{squad_id}")
    assert res.status_code == 200
    assert res.json()["id"] == squad_id

    # 5. Atualizar squad
    update_payload = {"description": "Nova descrição atualizada"}
    res = client.put(f"/api/squads/{squad_id}", json=update_payload)
    assert res.status_code == 200
    assert res.json()["description"] == "Nova descrição atualizada"

    # 6. Exportar squad (sem segredos)
    res = client.get(f"/api/squads/{squad_id}/export")
    assert res.status_code == 200
    exported = res.json()
    assert exported["squad"]["id"] == squad_id
    assert "api_key" not in json.dumps(exported)

    # 7. Importar squad
    exported["squad"]["id"] = "squad-imported-test"
    exported["squad"]["name"] = "Squad Importado de Teste"
    res = client.post("/api/squads/import", json=exported)
    assert res.status_code == 200
    assert res.json()["id"] == "squad-imported-test"

    # 8. Deletar squads de teste
    res = client.delete(f"/api/squads/{squad_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True

    res = client.delete("/api/squads/squad-imported-test")
    assert res.status_code == 200


def test_workflows_crud():
    client = TestClient(app)

    # 1. Listar workflows padrão
    res = client.get("/api/workflows")
    assert res.status_code == 200
    workflows = res.json()
    assert len(workflows) >= 1
    assert workflows[0]["id"] == "workflow-standard-engineering"

    # 2. Criar novo Workflow
    create_payload = {
        "name": "Workflow Rápido de Documentação",
        "description": "Workflow de 2 etapas para criação de docs",
        "steps": [
            {
                "id": "step-draft",
                "name": "Rascunho",
                "required_role": "writer",
                "action_type": "generate",
                "instructions": "Escreva o rascunho do guia técnico.",
                "requires_human_approval": False
            },
            {
                "id": "step-review",
                "name": "Revisão Final",
                "required_role": "qa",
                "action_type": "review",
                "instructions": "Revise a documentação para clareza.",
                "requires_human_approval": True
            }
        ]
    }
    res = client.post("/api/workflows", json=create_payload)
    assert res.status_code == 200
    new_wf = res.json()
    wf_id = new_wf["id"]
    assert new_wf["name"] == "Workflow Rápido de Documentação"
    assert len(new_wf["steps"]) == 2

    # 3. Consultar por ID
    res = client.get(f"/api/workflows/{wf_id}")
    assert res.status_code == 200
    assert res.json()["id"] == wf_id

    # 4. Atualizar workflow
    res = client.put(f"/api/workflows/{wf_id}", json={"description": "Descrição atualizada"})
    assert res.status_code == 200
    assert res.json()["description"] == "Descrição atualizada"

    # 5. Excluir workflow de teste
    res = client.delete(f"/api/workflows/{wf_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True


def test_tasks_crud_and_lifecycle():
    client = TestClient(app)

    # 1. Criar tarefa com workflow válido
    task_payload = {
        "title": "Implementar módulo de métricas",
        "objective": "Adicionar coleta de métricas em memória",
        "workflow_id": "workflow-standard-engineering"
    }
    res = client.post("/api/tasks", json=task_payload)
    assert res.status_code == 200
    task = res.json()
    task_id = task["id"]
    assert task["state"] == "QUEUED"
    assert len(task["events"]) >= 1
    assert task["events"][0]["event_type"] == "task.created"

    # 2. Consultar detalhes da tarefa
    res = client.get(f"/api/tasks/{task_id}")
    assert res.status_code == 200
    assert res.json()["id"] == task_id

    # 3. Atualizar metadados
    res = client.put(f"/api/tasks/{task_id}", json={"title": "Módulo de métricas v2"})
    assert res.status_code == 200
    assert res.json()["title"] == "Módulo de métricas v2"

    # 4. Cancelar tarefa
    res = client.post(f"/api/tasks/{task_id}/cancel")
    assert res.status_code == 200
    cancelled_task = res.json()
    assert cancelled_task["state"] == "CANCELLED"

    # 5. Excluir tarefa cancelada
    res = client.delete(f"/api/tasks/{task_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True


def test_state_machine_validations():
    """Testa transições permitidas e rejeição estrita de transições inválidas."""
    dummy_task = TaskPacket(
        id="task-sm-test",
        title="Teste de Transições",
        objective="Validar máquina de estados",
        workflow_id="wf-test",
        state=TaskState.QUEUED,
        created_at=time.time(),
        updated_at=time.time()
    )

    # QUEUED -> IN_PROGRESS (Válido)
    workflow_engine.transition_state(dummy_task, TaskState.IN_PROGRESS, reason="Início")
    assert dummy_task.state == TaskState.IN_PROGRESS

    # IN_PROGRESS -> WAITING_APPROVAL (Válido)
    workflow_engine.transition_state(dummy_task, TaskState.WAITING_APPROVAL, reason="Aguardando aprovação")
    assert dummy_task.state == TaskState.WAITING_APPROVAL

    # WAITING_APPROVAL -> COMPLETED (Válido)
    workflow_engine.transition_state(dummy_task, TaskState.COMPLETED, reason="Aprovado e finalizado")
    assert dummy_task.state == TaskState.COMPLETED

    # COMPLETED -> IN_PROGRESS (INVÁLIDO: estado terminal!)
    try:
        workflow_engine.transition_state(dummy_task, TaskState.IN_PROGRESS)
        assert False, "Deveria ter lançado InvalidTransitionError"
    except InvalidTransitionError:
        pass  # Sucesso: transição rejeitada

    # Teste de Retry: apenas FAILED pode ir para QUEUED
    failed_task = TaskPacket(
        id="task-failed-test",
        title="Falha",
        objective="Teste",
        workflow_id="wf-test",
        state=TaskState.FAILED,
        created_at=time.time(),
        updated_at=time.time()
    )
    workflow_engine.transition_state(failed_task, TaskState.QUEUED, reason="Retry autorizado")
    assert failed_task.state == TaskState.QUEUED


def test_concurrency_and_recovery():
    """Valida prevenção de concorrência duplicada e recuperação de tarefas interrompidas."""
    # 1. Simular tarefa ativa no motor
    workflow_engine._running_tasks.add("task-busy-1")
    assert workflow_engine.is_task_running("task-busy-1") is True

    client = TestClient(app)
    # Tentar iniciar tarefa já ocupada
    # Salvar tarefa no banco primeiro
    tasks_data = storage.load_tasks()
    busy_task = TaskPacket(
        id="task-busy-1",
        title="Ocupada",
        objective="Concorrência",
        workflow_id="workflow-standard-engineering",
        state=TaskState.QUEUED,
        created_at=time.time(),
        updated_at=time.time()
    )
    tasks_data.tasks.append(busy_task)
    storage.save_tasks(tasks_data)

    res = client.post("/api/tasks/task-busy-1/start")
    assert res.status_code == 400
    assert "já está em execução" in res.json()["detail"]

    # Liberar tarefa
    workflow_engine._running_tasks.discard("task-busy-1")

    # 2. Testar recuperação de tarefa interrompida por reinício
    interrupted_task = TaskPacket(
        id="task-interrupted-1",
        title="Interrompida",
        objective="Recuperação",
        workflow_id="workflow-standard-engineering",
        state=TaskState.IN_PROGRESS,
        created_at=time.time(),
        updated_at=time.time()
    )
    tasks_data.tasks.append(interrupted_task)
    storage.save_tasks(tasks_data)

    # Executar recuperação
    recovered_count = workflow_engine.recover_interrupted_tasks()
    assert recovered_count >= 1

    reloaded_tasks = storage.load_tasks()
    reloaded_task = next(t for t in reloaded_tasks.tasks if t.id == "task-interrupted-1")
    assert reloaded_task.state == TaskState.FAILED
    assert "reinício do servidor" in reloaded_task.events[-1].message

    # Limpeza
    reloaded_tasks.tasks = [t for t in reloaded_tasks.tasks if t.id not in ("task-busy-1", "task-interrupted-1")]
    storage.save_tasks(reloaded_tasks)


if __name__ == "__main__":
    print("Executando test_agent_templates_and_squads_crud...")
    test_agent_templates_and_squads_crud()
    print("Executando test_workflows_crud...")
    test_workflows_crud()
    print("Executando test_tasks_crud_and_lifecycle...")
    test_tasks_crud_and_lifecycle()
    print("Executando test_state_machine_validations...")
    test_state_machine_validations()
    print("Executando test_concurrency_and_recovery...")
    test_concurrency_and_recovery()
    print("\nTODOS OS TESTES DA ETAPA 2 (API E MÁQUINA DE ESTADOS) PASSARAM COM SUCESSO!")
