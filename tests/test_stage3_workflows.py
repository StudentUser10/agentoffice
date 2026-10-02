"""
AgentOffice 2D - Testes Automatizados da Etapa 3
Testa Quality Gates, Propostas de Alteração, Diffs Unificados,
Limites de Refação, Isolamento de Falhas e Aprovação Humana Segura (Sandbox).
"""

import asyncio
import os
import shutil
import sys
import tempfile
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
    TaskArtifact,
    TaskPacket,
    TasksData,
    TaskState,
    WorkflowActionType,
    WorkflowStep,
    WorkflowTemplate,
)
from backend.storage import storage
from backend.workflow_engine import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    InvalidTransitionError,
    SecurityPathError,
    workflow_engine,
)


def test_quality_gate_evaluations():
    """Valida a avaliação de quality gates, detecção de tags, palavras-chave e feedback."""
    print("--- Testando evaluate_quality_gate ---")

    # 1. Avaliação com aprovação explícita
    output_aprovado = (
        "DECISÃO: APROVADO\n"
        "CRITÉRIOS:\n"
        "- Conformidade com os requisitos: OK\n"
        "- Sem vulnerabilidades evidentes: OK\n"
        "FEEDBACK:\n"
        "A implementação está bem documentada e cumpre todos os requisitos do projeto."
    )
    is_ok, feedback, criteria = workflow_engine.evaluate_quality_gate(output_aprovado)
    assert is_ok is True
    assert "cumpre todos os requisitos" in feedback

    # 2. Avaliação com reprovação explícita e extração de feedback
    output_reprovado = (
        "DECISÃO: REPROVADO\n"
        "CRITÉRIOS:\n"
        "- Tratamento de exceções: FALHOU\n"
        "FEEDBACK:\n"
        "Faltou capturar exceções de rede e os testes automatizados não cobrem caminhos de falha."
    )
    is_ok, feedback, criteria = workflow_engine.evaluate_quality_gate(output_reprovado)
    assert is_ok is False
    assert "Faltou capturar exceções" in feedback

    # 3. Validação de rejeição automática via palavra-chave proibida
    output_auto_reject = (
        "DECISÃO: APROVADO\n"
        "O código funciona bem, porém contém SYNTAX_ERROR simulado para testes."
    )
    is_ok, feedback, criteria = workflow_engine.evaluate_quality_gate(
        output_auto_reject,
        auto_reject_keywords=["SYNTAX_ERROR", "SECURITY_VULN"]
    )
    assert is_ok is False
    assert "SYNTAX_ERROR" in feedback

    # 4. Fallback em texto sem tag estruturada
    output_prosa_negativa = "Infelizmente o código foi reprovado pois falhou na validação de tipos."
    is_ok, feedback, _ = workflow_engine.evaluate_quality_gate(output_prosa_negativa)
    assert is_ok is False

    output_prosa_positiva = "O artefato foi analisado e atende perfeitamente ao esperado."
    is_ok, feedback, _ = workflow_engine.evaluate_quality_gate(output_prosa_positiva)
    assert is_ok is True


def test_change_proposals_and_diff_generation():
    """Valida extração de propostas de alteração e geração de diffs unificados sem escrita no disco."""
    print("--- Testando propostas e diffs unificados ---")

    # 1. Extração estruturada de proposta
    raw_llm_output = (
        "ARQUIVO_ALVO: src/utils/math.py\n"
        "RESUMO: Adiciona função para cálculo de fatorial\n"
        "CONTEUDO_PROPOSTO:\n"
        "def factorial(n: int) -> int:\n"
        "    if n <= 1:\n"
        "        return 1\n"
        "    return n * factorial(n - 1)\n"
    )
    affected_file, summary, proposed_content = workflow_engine.parse_change_proposal(raw_llm_output)
    assert affected_file == "src/utils/math.py"
    assert "fatorial" in summary
    assert "def factorial" in proposed_content

    # 2. Geração de diff unificado com arquivo existente
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file = Path(temp_dir) / "config.txt"
        test_file.write_text("port=8000\ndebug=true\n", encoding="utf-8")

        new_content = "port=8080\ndebug=false\nssl=true\n"
        diff = workflow_engine.generate_unified_diff("config.txt", new_content, temp_dir)

        assert "--- a/config.txt" in diff
        assert "+++ b/config.txt" in diff
        assert "-port=8000" in diff
        assert "+port=8080" in diff
        assert "+ssl=true" in diff

        # CRUCIAL: Garantir que o arquivo original em disco NÃO FOI MODIFICADO
        assert test_file.read_text(encoding="utf-8") == "port=8000\ndebug=true\n"

    # 3. Geração de diff para arquivo novo
    with tempfile.TemporaryDirectory() as temp_dir:
        diff_novo = workflow_engine.generate_unified_diff("novo.py", "x = 10\n", temp_dir)
        assert "--- /dev/null" in diff_novo or "--- a/novo.py" in diff_novo
        assert "+x = 10" in diff_novo
        assert not (Path(temp_dir) / "novo.py").exists()


def test_quality_gate_workflow_execution():
    """Valida o motor de execução com quality gates: aprovação, refação, limite de revisões e timeout."""
    print("--- Testando execução do motor com Quality Gates ---")

    tasks_data = storage.load_tasks()
    tasks_data.tasks = [t for t in tasks_data.tasks if not t.id.startswith("task-qg-") and not t.id.startswith("debug-")]
    storage.save_tasks(tasks_data)

    workflows_data = storage.load_workflows()
    workflows_data.workflows = [w for w in workflows_data.workflows if w.id != "wf-test-qg"]

    # Criar um workflow de teste com etapa de geração e etapa de revisão
    wf_id = "wf-test-qg"
    custom_wf = WorkflowTemplate(
        id=wf_id,
        name="Workflow de Teste Quality Gate",
        description="Testa revisão e limite de refações",
        steps=[
            WorkflowStep(
                id="step-dev",
                name="Desenvolvimento",
                required_role="developer",
                action_type=WorkflowActionType.GENERATE,
                instructions="Escreva a função"
            ),
            WorkflowStep(
                id="step-qa",
                name="Revisão de QA",
                required_role="qa",
                action_type=WorkflowActionType.REVIEW,
                instructions="Avalie a qualidade",
                review_criteria=["Testes passando", "Código limpo"],
                max_revisions=2
            )
        ]
    )
    workflows_data.workflows.append(custom_wf)
    storage.save_workflows(workflows_data)

    # CENÁRIO A: QA Aprova a entrega -> Tarefa completa com sucesso
    task_approved = TaskPacket(
        id="task-qg-approved",
        title="Tarefa com QA Aprovando",
        objective="Validar avanço normal de quality gate",
        workflow_id=wf_id,
        current_step_index=1,  # Inicia direto na etapa de QA
        state=TaskState.IN_PROGRESS,
        created_at=time.time(),
        updated_at=time.time()
    )
    tasks_data.tasks.append(task_approved)
    storage.save_tasks(tasks_data)

    with patch("backend.workflow_engine.LLMClient.generate_response", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "DECISÃO: APROVADO\nFEEDBACK: Tudo correto."
        asyncio.run(workflow_engine.execute_task("task-qg-approved"))

    reloaded = next(t for t in storage.load_tasks().tasks if t.id == "task-qg-approved")
    assert reloaded.state == TaskState.COMPLETED
    assert any(e.payload.get("result") == "passed" for e in reloaded.events if e.event_type == "task.quality_gate_event")

    # CENÁRIO B: QA Reprova com revisões restantes -> Devolve para refação (IN_PROGRESS)
    task_rejected_under_limit = TaskPacket(
        id="task-qg-retry",
        title="Tarefa com QA Reprovando",
        objective="Validar devolução e refação",
        workflow_id=wf_id,
        current_step_index=1,
        state=TaskState.IN_PROGRESS,
        revision_count=0,
        created_at=time.time(),
        updated_at=time.time()
    )
    tasks_data = storage.load_tasks()
    tasks_data.tasks.append(task_rejected_under_limit)
    storage.save_tasks(tasks_data)

    with patch("backend.workflow_engine.LLMClient.generate_response", new_callable=AsyncMock) as mock_llm:
        # Primeira chamada (QA) reprova, segunda chamada (Dev na refação) produz código
        mock_llm.side_effect = [
            "DECISÃO: REPROVADO\nFEEDBACK: Faltou tratar None.",
            "Código corrigido com tratamento de None."
        ]
        # Interromper após o loop avançar para não rodar infinito
        asyncio.run(workflow_engine.execute_task("task-qg-retry"))

    reloaded = next(t for t in storage.load_tasks().tasks if t.id == "task-qg-retry")
    assert reloaded.revision_count >= 1
    assert any(e.payload.get("result") == "rejected" for e in reloaded.events if e.event_type == "task.quality_gate_event")

    # CENÁRIO C: QA Reprova atingindo o limite de revisões (max_revisions=2)
    # -> Pausa para intervenção humana em WAITING_APPROVAL
    task_limit_reached = TaskPacket(
        id="task-qg-limit",
        title="Tarefa Limite Atingido",
        objective="Validar pausa para intervenção do usuário",
        workflow_id=wf_id,
        current_step_index=1,
        state=TaskState.IN_PROGRESS,
        revision_count=2,  # Já atingiu o máximo configurado (2)
        created_at=time.time(),
        updated_at=time.time()
    )
    tasks_data = storage.load_tasks()
    tasks_data.tasks.append(task_limit_reached)
    storage.save_tasks(tasks_data)

    with patch("backend.workflow_engine.LLMClient.generate_response", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "DECISÃO: REPROVADO\nFEEDBACK: Persiste com erro de concorrência."
        asyncio.run(workflow_engine.execute_task("task-qg-limit"))

    reloaded = next(t for t in storage.load_tasks().tasks if t.id == "task-qg-limit")
    assert reloaded.state == TaskState.WAITING_APPROVAL
    assert len(reloaded.approvals) == 1
    assert "Limite de revisões" in reloaded.approvals[0].summary

    # CENÁRIO D: Falha/Timeout no revisor -> Marca FAILED e não considera aprovada
    task_timeout = TaskPacket(
        id="task-qg-timeout",
        title="Tarefa com Revisor em Timeout",
        objective="Validar não-aprovação em caso de falha técnica",
        workflow_id=wf_id,
        current_step_index=1,
        state=TaskState.IN_PROGRESS,
        created_at=time.time(),
        updated_at=time.time()
    )
    tasks_data = storage.load_tasks()
    tasks_data.tasks.append(task_timeout)
    storage.save_tasks(tasks_data)

    with patch("backend.workflow_engine.LLMClient.generate_response", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = TimeoutError("Ollama request timed out after 45.0s")
        asyncio.run(workflow_engine.execute_task("task-qg-timeout"))

    reloaded = next(t for t in storage.load_tasks().tasks if t.id == "task-qg-timeout")
    assert reloaded.state == TaskState.FAILED
    assert "timed out" in reloaded.events[-1].message.lower()

    # Limpeza
    all_tasks = storage.load_tasks()
    all_tasks.tasks = [t for t in all_tasks.tasks if not t.id.startswith("task-qg-")]
    storage.save_tasks(all_tasks)
    wfs = storage.load_workflows()
    wfs.workflows = [w for w in wfs.workflows if w.id != wf_id]
    storage.save_workflows(wfs)


def test_human_approval_api_endpoints_and_safety():
    """Valida os endpoints REST de aprovação/rejeição, aplicação atômica e segurança de sandbox."""
    print("--- Testando endpoints REST de aprovação e sandbox de arquivos ---")
    client = TestClient(app)

    task_id = "task-approval-test-1"
    appr_id = "appr-valid-1"
    malicious_task_id = "task-malicious-traversal"
    reject_task_id = "task-reject-test"
    reject_task_id_2 = "task-reject-fail-test"

    with tempfile.TemporaryDirectory() as temp_ws:
        # Configurar pasta de trabalho temporária
        cfg = storage.load_config()
        original_ws = cfg.workspace_dir
        cfg.workspace_dir = temp_ws
        storage.save_config(cfg)

        try:
            # 1. Criar tarefa em WAITING_APPROVAL com proposta válida
            tasks_data = storage.load_tasks()

            pending_approval = ApprovalRequest(
                id=appr_id,
                task_id=task_id,
                step_id="step-prepare",
                summary="Criação de script de inicialização",
                proposed_diff="--- /dev/null\n+++ b/scripts/init.py\n@@ Novo @@\n+print('ready')\n",
                proposed_content="print('ready')\n",
                affected_file="scripts/init.py",
                status="pending",
                created_at=time.time()
            )

            test_task = TaskPacket(
                id=task_id,
                title="Tarefa com Aprovação Humana",
                objective="Testar fluxo de aprovação e escrita segura",
                workflow_id="workflow-standard-engineering",
                current_step_index=0,
                state=TaskState.WAITING_APPROVAL,
                approvals=[pending_approval],
                created_at=time.time(),
                updated_at=time.time()
            )
            tasks_data.tasks.append(test_task)
            storage.save_tasks(tasks_data)

            # 2. Consultar aprovações pendentes
            res = client.get("/api/approvals/pending")
            assert res.status_code == 200
            pending_list = res.json()
            assert any(a["id"] == appr_id for a in pending_list)

            # 3. Consultar histórico de aprovações da tarefa
            res = client.get(f"/api/tasks/{task_id}/approvals")
            assert res.status_code == 200
            assert len(res.json()) == 1
            assert res.json()[0]["id"] == appr_id

            # 4. Aprovar a proposta via POST /api/tasks/{task_id}/approvals/{approval_id}/approve
            with patch.object(workflow_engine, "execute_task", new_callable=AsyncMock):
                res = client.post(
                    f"/api/tasks/{task_id}/approvals/{appr_id}/approve",
                    json={"notes": "Aprovado com sucesso pela liderança técnica"}
                )
            assert res.status_code == 200
            updated_task = res.json()
            assert updated_task["approvals"][0]["status"] == "approved"
            assert "Aprovado com sucesso" in updated_task["approvals"][0]["feedback"]

            # 5. Confirmar que o arquivo foi gravado de fato dentro da pasta de trabalho
            written_file = Path(temp_ws) / "scripts" / "init.py"
            assert written_file.exists()
            assert written_file.read_text(encoding="utf-8") == "print('ready')\n"

            # 6. Tentar aprovar novamente uma aprovação já decidida -> Retorna 400
            res = client.post(f"/api/tasks/{task_id}/approvals/{appr_id}/approve", json={})
            assert res.status_code == 400
            assert "já foi decidida" in res.json()["detail"]

            # 7. Teste de Segurança: Proposta maliciosa com Path Traversal
            # Deve ser terminantemente rejeitada pelo sandbox e não escrever nada
            malicious_task_id = "task-malicious-traversal"
            malicious_appr_id = "appr-malicious-1"

            outside_file = Path(temp_ws).parent / "outside_evil.txt"
            if outside_file.exists():
                outside_file.unlink()

            malicious_approval = ApprovalRequest(
                id=malicious_appr_id,
                task_id=malicious_task_id,
                step_id="step-evil",
                summary="Tentativa de traversal",
                proposed_diff="--- /dev/null\n+++ b/outside.txt\n",
                proposed_content="malicious payload",
                affected_file="../../outside_evil.txt",
                status="pending",
                created_at=time.time()
            )

            malicious_task = TaskPacket(
                id=malicious_task_id,
                title="Ataque Path Traversal",
                objective="Testar bloqueio de segurança",
                workflow_id="workflow-standard-engineering",
                current_step_index=0,
                state=TaskState.WAITING_APPROVAL,
                approvals=[malicious_approval],
                created_at=time.time(),
                updated_at=time.time()
            )
            tasks_data = storage.load_tasks()
            tasks_data.tasks.append(malicious_task)
            storage.save_tasks(tasks_data)

            # Tenta aprovar caminho malicioso
            res = client.post(f"/api/tasks/{malicious_task_id}/approvals/{malicious_appr_id}/approve", json={})
            assert res.status_code == 400
            assert "Caminho inseguro detectado" in res.json()["detail"]
            assert not outside_file.exists(), "FALHA GRAVE: Arquivo foi gravado fora da pasta de trabalho!"

            # 8. Teste de Rejeição de Proposta com Retry
            reject_task_id = "task-reject-test"
            reject_appr_id = "appr-reject-1"
            reject_approval = ApprovalRequest(
                id=reject_appr_id,
                task_id=reject_task_id,
                step_id="step-1",
                summary="Mudança descartável",
                proposed_diff="diff",
                proposed_content="draft",
                affected_file="draft.txt",
                status="pending",
                created_at=time.time()
            )
            reject_task = TaskPacket(
                id=reject_task_id,
                title="Tarefa a Rejeitar",
                objective="Testar recusa de proposta",
                workflow_id="workflow-standard-engineering",
                current_step_index=0,
                state=TaskState.WAITING_APPROVAL,
                revision_count=0,
                approvals=[reject_approval],
                created_at=time.time(),
                updated_at=time.time()
            )
            tasks_data = storage.load_tasks()
            tasks_data.tasks.append(reject_task)
            storage.save_tasks(tasks_data)

            with patch.object(workflow_engine, "execute_task", new_callable=AsyncMock):
                res = client.post(
                    f"/api/tasks/{reject_task_id}/approvals/{reject_appr_id}/reject",
                    json={"notes": "Solução inadequada, refazer com outra arquitetura.", "action": "retry"}
                )
            assert res.status_code == 200
            rej_task = res.json()
            assert rej_task["state"] == TaskState.IN_PROGRESS
            assert rej_task["revision_count"] == 1
            assert rej_task["approvals"][0]["status"] == "rejected"
            assert not (Path(temp_ws) / "draft.txt").exists()

            # 9. Teste de Rejeição definitiva (action="fail" ou padrão)
            reject_task_id_2 = "task-reject-fail-test"
            reject_appr_id_2 = "appr-reject-fail-1"
            reject_approval_2 = ApprovalRequest(
                id=reject_appr_id_2,
                task_id=reject_task_id_2,
                step_id="step-1",
                summary="Mudança cancelada",
                status="pending",
                created_at=time.time()
            )
            reject_task_2 = TaskPacket(
                id=reject_task_id_2,
                title="Tarefa a Rejeitar Definitivo",
                objective="Testar falha na rejeição",
                workflow_id="workflow-standard-engineering",
                current_step_index=0,
                state=TaskState.WAITING_APPROVAL,
                approvals=[reject_approval_2],
                created_at=time.time(),
                updated_at=time.time()
            )
            tasks_data = storage.load_tasks()
            tasks_data.tasks.append(reject_task_2)
            storage.save_tasks(tasks_data)

            res = client.post(
                f"/api/tasks/{reject_task_id_2}/approvals/{reject_appr_id_2}/reject",
                json={"notes": "Projeto cancelado pelo cliente"}
            )
            assert res.status_code == 200
            assert res.json()["state"] == TaskState.FAILED

        finally:
            # Restaurar workspace original e limpar tarefas criadas
            cfg.workspace_dir = original_ws
            storage.save_config(cfg)

            all_tasks = storage.load_tasks()
            all_tasks.tasks = [
                t for t in all_tasks.tasks
                if t.id not in (task_id, malicious_task_id, reject_task_id, reject_task_id_2)
            ]
            storage.save_tasks(all_tasks)


if __name__ == "__main__":
    print("Iniciando bateria de testes automatizados da Etapa 3...\n")
    test_quality_gate_evaluations()
    test_change_proposals_and_diff_generation()
    test_quality_gate_workflow_execution()
    test_human_approval_api_endpoints_and_safety()
    print("\nTODOS OS TESTES DA ETAPA 3 (QUALITY GATES E APROVAÇÃO HUMANA) PASSARAM COM SUCESSO!")
