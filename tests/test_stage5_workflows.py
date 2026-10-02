"""
AgentOffice 2D - Testes Automatizados da Etapa 5 (Canvas, Diagnóstico e Relatórios)
Valida:
1. Endpoints e motor de diagnóstico do sistema (/api/system/diagnostics e /api/system/diagnostics/run)
2. Transmissão do evento WebSocket system.diagnostic_result
3. Geração automática e segura do relatório final Markdown no workspace
4. Verificação de ausência de chaves de API, senhas ou raciocínios internos no relatório
5. Endpoint de consulta do relatório (/api/tasks/{task_id}/report)
6. Objetos interativos do Canvas 2D (Quadro Branco e Rack de Servidores) e colisão AABB
7. Métodos visuais de handoff e estados dos agentes
"""

import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app import app
from backend.config import BASE_DIR, DATA_DIR
from backend.diagnostics import run_system_diagnostics
from backend.models import (
    ApprovalRequest,
    DiagnosticResult,
    TaskArtifact,
    TaskEvent,
    TaskPacket,
    TaskState,
    WorkflowActionType,
    WorkflowStep,
    WorkflowTemplate,
)
from backend.storage import storage
from backend.workflow_engine import workflow_engine


def test_system_diagnostics_engine_and_api():
    """Valida o motor de diagnósticos, schemas Pydantic e endpoints REST."""
    print("--- Testando Motor de Diagnósticos do Sistema ---")
    client = TestClient(app)

    # 1. Execução direta da função de diagnóstico assíncrona
    import asyncio
    diag = asyncio.run(run_system_diagnostics())
    assert isinstance(diag, DiagnosticResult)
    assert diag.overall_status in ("healthy", "warning", "error")
    assert len(diag.items) >= 4

    # Verificar que nenhum segredo/chave de API foi exposto
    for item in diag.items:
        assert item.name
        assert item.status in ("healthy", "warning", "error")
        assert item.message
        if item.details:
            details_str = str(item.details).lower()
            assert "sk-" not in details_str
            assert "api_key" not in item.details

    # 2. Endpoint GET /api/system/diagnostics
    res_get = client.get("/api/system/diagnostics")
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert "overall_status" in data_get
    assert "items" in data_get
    assert "system_info" in data_get
    assert data_get["system_info"]["server_host"] == "127.0.0.1:8000"

    # 3. Endpoint POST /api/system/diagnostics/run com broadcast WebSocket
    with client.websocket_connect("/ws", headers={"origin": "http://127.0.0.1:8000"}) as ws:
        ws.receive_json()  # workspace.updated

        res_run = client.post("/api/system/diagnostics/run")
        assert res_run.status_code == 200
        data_run = res_run.json()
        assert data_run["overall_status"] in ("healthy", "warning", "error")

        # WebSocket deve receber evento system.diagnostic_result
        ws_msg = ws.receive_json()
        assert ws_msg.get("event") == "system.diagnostic_result"
        assert "payload" in ws_msg
        assert ws_msg["payload"]["overall_status"] == data_run["overall_status"]


def test_markdown_report_generation_and_api():
    """Valida a geração do relatório Markdown no workspace e seu consumo via API."""
    print("--- Testando Geração e Consulta do Relatório Markdown ---")
    client = TestClient(app)

    config = storage.load_config()
    workspace_dir = Path(config.workspace_dir or str(BASE_DIR)).resolve()

    task_id = "task-report-test-01"
    clean_report_name = f"relatorio_tarefa_{task_id}.md"
    report_file_path = workspace_dir / clean_report_name
    if report_file_path.exists():
        report_file_path.unlink()

    # Cria pacote de tarefa completo simulando ciclo de vida concluído
    task = TaskPacket(
        id=task_id,
        title="Construção de Módulo de Pagamento Seguro",
        objective="Implementar fluxo de checkout idempotente com conciliação bancária",
        workflow_id="workflow-standard-engineering",
        current_step_index=2,
        state=TaskState.COMPLETED,
        assigned_agent_id="agent-techlead",
        summary="Módulo de pagamentos entregue e revisado com sucesso.",
        revision_count=1,
        decisions=[
            "[Desenvolvimento] Arquivo payment_gateway.py gerado.",
            "[Revisão - QA] APROVADO por QA Lead."
        ],
        artifacts=[
            TaskArtifact(
                id="art-code-01",
                name="Módulo Gateway",
                file_path="backend/payment_gateway.py",
                content_type="text/x-python",
                content="class PaymentGateway: pass\n",
                created_at=time.time() - 30
            )
        ],
        approvals=[
            ApprovalRequest(
                id="appr-rep-01",
                task_id=task_id,
                step_id="step-prepare",
                summary="Criação do gateway de pagamento",
                affected_file="backend/payment_gateway.py",
                status="approved",
                feedback="Código aprovado para produção",
                created_at=time.time() - 20,
                decided_at=time.time() - 5
            )
        ],
        events=[
            TaskEvent(
                id="evt-rep-01",
                task_id=task_id,
                event_type="task.quality_gate_event",
                message="Quality gate aprovado por Alex Tech Lead",
                timestamp=time.time() - 10,
                payload={"step_name": "Revisão de Código", "result": "passed", "feedback": "Sem vulnerabilidades"}
            )
        ],
        created_at=time.time() - 60,
        updated_at=time.time()
    )

    # 1. Geração do relatório pelo motor
    filename, md_content = workflow_engine.generate_final_report(task)
    assert filename == clean_report_name
    assert report_file_path.exists(), "O arquivo Markdown deve ser gravado fisicamente no workspace."

    disk_content = report_file_path.read_text(encoding="utf-8")
    assert disk_content == md_content

    # 2. Verificação obrigatória dos campos da Seção 4.H
    assert "# Relatório Final de Execução de Tarefa" in md_content
    assert "## 1. Resumo da Tarefa" in md_content
    assert task.title in md_content
    assert task.objective in md_content
    assert "## 2. Etapas Executadas" in md_content
    assert "## 3. Agentes Envolvidos" in md_content
    assert "## 4. Duração Total" in md_content
    assert "## 5. Arquivos Criados ou Modificados" in md_content
    assert "backend/payment_gateway.py" in md_content
    assert "## 6. Resultados dos Quality Gates" in md_content
    assert "Sem vulnerabilidades" in md_content
    assert "## 7. Aprovações e Recusas Humanas" in md_content
    assert "Código aprovado para produção" in md_content
    assert "## 8. Erros, Avisos ou Limitações" in md_content

    # 3. Garantia de que segredos, chaves e pensamentos de modelo NÃO estão presentes
    assert "sk-proj-" not in md_content and "sk-ant-" not in md_content
    assert "api_key" not in md_content.lower()
    assert "chain-of-thought" not in md_content.lower()

    # 4. Salvar no storage para testar API de consulta
    tasks_data = storage.load_tasks()
    tasks_data.tasks = [t for t in tasks_data.tasks if t.id != task_id] + [task]
    storage.save_tasks(tasks_data)

    res_api = client.get(f"/api/tasks/{task_id}/report")
    assert res_api.status_code == 200
    api_data = res_api.json()
    assert api_data["task_id"] == task_id
    assert api_data["report_filename"] == clean_report_name
    assert "# Relatório Final" in api_data["content"]

    # Limpeza
    if report_file_path.exists():
        report_file_path.unlink()
    tasks_data.tasks = [t for t in tasks_data.tasks if t.id != task_id]
    storage.save_tasks(tasks_data)


def test_canvas_engine_and_diagnostics_frontend_integration():
    """Valida a existência dos componentes do frontend da Etapa 5."""
    print("--- Testando Componentes Frontend da Etapa 5 ---")

    frontend_dir = BASE_DIR / "frontend"
    js_dir = frontend_dir / "js"
    css_dir = frontend_dir / "css"

    # 1. Arquivo de Diagnósticos JS
    diag_js = js_dir / "diagnostics.js"
    assert diag_js.exists(), "frontend/js/diagnostics.js deve existir."
    diag_code = diag_js.read_text(encoding="utf-8")
    assert "OfficeDiagnostics" in diag_code
    assert "system.diagnostic_result" in diag_code
    assert "/api/system/diagnostics" in diag_code

    # 2. engine.js atualizado com Quadro e Rack
    engine_js = js_dir / "engine.js"
    engine_code = engine_js.read_text(encoding="utf-8")
    assert "Rack de Servidores" in engine_code
    assert "Quadro Branco" in engine_code
    assert "interactiveObjects" in engine_code
    assert "triggerHandoff" in engine_code
    assert "waiting_approval" in engine_code
    assert "reviewing" in engine_code

    # 3. index.html com modal de diagnóstico e script tags
    index_html = (frontend_dir / "index.html").read_text(encoding="utf-8")
    assert "diagnosticsModal" in index_html
    assert "openDiagnosticsBtn" in index_html
    assert "diagnostics.js" in index_html

    # 4. style.css com estilos para diagnóstico e previewer de relatório
    style_css = (css_dir / "style.css").read_text(encoding="utf-8")
    assert "diagnostics-modal-card" in style_css
    assert "report-markdown-preview" in style_css
    assert "diag-status-healthy" in style_css


if __name__ == "__main__":
    print("Iniciando bateria de testes automatizados da Etapa 5...\n")
    test_system_diagnostics_engine_and_api()
    test_markdown_report_generation_and_api()
    test_canvas_engine_and_diagnostics_frontend_integration()
    print("\nTODOS OS TESTES DA ETAPA 5 (CANVAS, DIAGNÓSTICO E RELATÓRIOS) PASSARAM COM SUCESSO!")
