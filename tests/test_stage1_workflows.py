"""
Testes Automatizados da Etapa 1 (Modelos e Persistência do Workflow Engine)
Verifica modelos Pydantic, armazenamento atômico, criação de backups, recuperação
de arquivos corrompidos, importação/exportação segura de squads e segurança de caminhos.
"""

import sys
import json
import tempfile
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.config import is_safe_workspace_child_path
from backend.models import (
    AgentRoleType,
    AgentTemplate,
    ApprovalRequest,
    DiagnosticResult,
    QualityGateRule,
    Squad,
    SquadExport,
    SquadsData,
    TaskArtifact,
    TaskEvent,
    TaskPacket,
    TasksData,
    TaskState,
    VALID_TASK_TRANSITIONS,
    WorkflowActionType,
    WorkflowStep,
    WorkflowsData,
    WorkflowTemplate,
)
from backend.storage import Storage


def test_models_and_enums_validation():
    """Valida todos os enums e modelos Pydantic da camada de workflows."""
    # 1. Estados da tarefa
    states = [s.value for s in TaskState]
    expected_states = [
        "QUEUED", "IN_PROGRESS", "QUALITY_GATE",
        "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"
    ]
    assert set(states) == set(expected_states)

    # 2. Transições válidas
    assert TaskState.IN_PROGRESS in VALID_TASK_TRANSITIONS[TaskState.QUEUED]
    assert TaskState.QUALITY_GATE in VALID_TASK_TRANSITIONS[TaskState.IN_PROGRESS]
    assert TaskState.WAITING_APPROVAL in VALID_TASK_TRANSITIONS[TaskState.IN_PROGRESS]
    assert TaskState.COMPLETED in VALID_TASK_TRANSITIONS[TaskState.IN_PROGRESS]
    assert VALID_TASK_TRANSITIONS[TaskState.COMPLETED] == []  # Terminal

    # 3. Modelos de templates de agentes
    agent_tmpl = AgentTemplate(
        id="tmpl-dev",
        name="Dev Sênior",
        title="Engenheiro Python",
        role_type=AgentRoleType.WORKER,
        system_prompt="Escreva código testável e modular."
    )
    assert agent_tmpl.role_type == AgentRoleType.WORKER

    # 4. Modelos de Squad e Exportação segura
    squad = Squad(
        id="squad-1",
        name="Squad Alpha",
        description="Squad de testes",
        agent_ids=["tmpl-dev"],
        created_at=time.time()
    )
    export_pkg = SquadExport(
        squad=squad,
        agent_templates=[agent_tmpl]
    )
    serialized = export_pkg.model_dump()
    assert "squad" in serialized
    assert "agent_templates" in serialized
    # Garante que nenhum campo de chave ou credencial existe no schema
    assert "api_key" not in json.dumps(serialized)
    assert "api_keys" not in json.dumps(serialized)

    # 5. Modelos de Workflow e Quality Gates
    qg_rule = QualityGateRule(
        id="qg-1",
        name="Lint e Tipagem",
        required_criteria=["Sem erros de sintaxe", "100% tipado"],
        max_retries=2
    )
    assert qg_rule.max_retries == 2

    step = WorkflowStep(
        id="step-1",
        name="Desenvolvimento",
        required_role="worker",
        action_type=WorkflowActionType.PREPARE_CHANGE,
        instructions="Implemente o componente solicitado.",
        requires_human_approval=True
    )
    workflow = WorkflowTemplate(
        id="wf-1",
        name="Feature Workflow",
        description="Workflow padrão para novas features",
        steps=[step]
    )
    assert workflow.steps[0].action_type == WorkflowActionType.PREPARE_CHANGE

    # 6. Pacote de tarefa e artefatos
    artifact = TaskArtifact(
        id="art-1",
        name="main.py diff",
        file_path="src/main.py",
        diff="+ def nova_func(): pass",
        created_at=time.time()
    )
    approval = ApprovalRequest(
        id="appr-1",
        task_id="task-1",
        step_id="step-1",
        summary="Criação da função nova_func()",
        affected_file="src/main.py",
        created_at=time.time()
    )
    task = TaskPacket(
        id="task-1",
        title="Criar endpoint de status",
        objective="Adicionar rota /status",
        workflow_id="wf-1",
        state=TaskState.QUEUED,
        artifacts=[artifact],
        approvals=[approval],
        created_at=time.time(),
        updated_at=time.time()
    )
    assert task.state == TaskState.QUEUED
    assert len(task.artifacts) == 1
    assert task.approvals[0].status == "pending"


def test_atomic_storage_and_defaults():
    """Valida gravação atômica, carregamento de templates padrão e rotação de backups."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        store = Storage(data_dir=tmp_path)
        store.ensure_initial_data()

        # 1. Verificar criação automática dos 5 arquivos essenciais
        assert (tmp_path / "config.json").exists()
        assert (tmp_path / "workspace.json").exists()
        assert (tmp_path / "squads.json").exists()
        assert (tmp_path / "workflows.json").exists()
        assert (tmp_path / "tasks.json").exists()

        # 2. Verificar templates de agentes e squad inicial padrão
        squads_data = store.load_squads()
        template_ids = [t.id for t in squads_data.templates]
        assert "template-tech-lead" in template_ids
        assert "template-python-dev" in template_ids
        assert "template-qa" in template_ids
        assert "template-analyst" in template_ids
        assert "template-writer" in template_ids
        assert len(squads_data.squads) >= 1
        assert squads_data.squads[0].id == "squad-core-engineering"

        # 3. Verificar workflow padrão inicial
        workflows_data = store.load_workflows()
        assert len(workflows_data.workflows) >= 1
        wf = workflows_data.workflows[0]
        assert wf.id == "workflow-standard-engineering"
        assert len(wf.steps) == 4
        step_names = [s.name for s in wf.steps]
        assert "Planejamento Arquitetural" in step_names
        assert "Execução & Proposta de Código" in step_names
        assert "Revisão de Qualidade & Testes" in step_names
        assert "Relatório Final & Conclusão" in step_names

        # 4. Modificar dados e validar criação atômica de backup
        new_task = TaskPacket(
            id="task-test-atomic",
            title="Tarefa de Teste",
            objective="Verificar atomicidade",
            workflow_id="wf-test",
            created_at=time.time(),
            updated_at=time.time()
        )
        tasks_data = TasksData(tasks=[new_task])
        store.save_tasks(tasks_data, backup=True)

        loaded_tasks = store.load_tasks()
        assert len(loaded_tasks.tasks) == 1
        assert loaded_tasks.tasks[0].id == "task-test-atomic"

        # Backup de tasks_*.bak deve ter sido gerado
        backups = list((tmp_path / "backups").glob("tasks_*.bak"))
        assert len(backups) >= 1, "Backup antes de salvar tarefas deve existir"


def test_corrupted_file_recovery_and_preservation():
    """Garante que arquivos corrompidos são preservados como .corrupt e recuperados com segurança."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        store = Storage(data_dir=tmp_path)
        store.ensure_initial_data()

        # Corromper propositalmente o workflows.json
        workflows_file = tmp_path / "workflows.json"
        with open(workflows_file, "w", encoding="utf-8") as f:
            f.write("{ JSON CORROMPIDO INCOMPLETO:")

        # Ao carregar, não deve quebrar: deve preservar cópia .corrupt e recriar o padrão seguro
        recovered_wf = store.load_workflows()
        assert recovered_wf is not None
        assert len(recovered_wf.workflows) >= 1

        corrupt_copies = list(tmp_path.glob("workflows.json.corrupt.*"))
        assert len(corrupt_copies) >= 1, "Arquivo corrompido original deve ser preservado para auditoria"

        # Corromper tasks.json
        tasks_file = tmp_path / "tasks.json"
        with open(tasks_file, "w", encoding="utf-8") as f:
            f.write("[[[[[ DADO INVALIDO")

        recovered_tasks = store.load_tasks()
        assert recovered_tasks is not None
        assert len(recovered_tasks.tasks) == 0

        corrupt_task_copies = list(tmp_path.glob("tasks.json.corrupt.*"))
        assert len(corrupt_task_copies) >= 1, "Cópia corrompida de tasks.json deve ser preservada"


def test_squad_export_and_import():
    """Testa exportação e importação de squads validando higienização e ausência de segredos."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        store = Storage(data_dir=tmp_path)
        store.ensure_initial_data()

        # Exportar squad core inicial
        export_pkg = store.export_squad("squad-core-engineering")
        assert export_pkg.squad.id == "squad-core-engineering"
        assert len(export_pkg.agent_templates) == 3

        # Criar um novo squad em memória para importar
        custom_squad = Squad(
            id="squad-custom-imported",
            name="Squad Importado Externo",
            description="Squad vindo de exportação externa",
            agent_ids=["template-python-dev", "template-qa"],
            created_at=time.time()
        )
        custom_pkg = SquadExport(
            version="1.0",
            squad=custom_squad,
            agent_templates=[]
        )

        imported = store.import_squad(custom_pkg)
        assert imported.id == "squad-custom-imported"

        # Verificar se está persistido em squads.json
        squads_reload = store.load_squads()
        squad_ids = [s.id for s in squads_reload.squads]
        assert "squad-custom-imported" in squad_ids


def test_safe_workspace_child_path_security():
    """Valida as restrições estritas de segurança para manipulação de arquivos do workspace."""
    with tempfile.TemporaryDirectory() as tmp_ws:
        ws_root = str(Path(tmp_ws).resolve())

        # 1. Arquivos válidos dentro do workspace
        assert is_safe_workspace_child_path("main.py", ws_root) is True
        assert is_safe_workspace_child_path("src/module.py", ws_root) is True
        assert is_safe_workspace_child_path(str(Path(ws_root) / "output" / "report.md"), ws_root) is True

        # 2. Rejeição de Path Traversal
        assert is_safe_workspace_child_path("../outside.py", ws_root) is False
        assert is_safe_workspace_child_path("sub/../../escape.py", ws_root) is False
        assert is_safe_workspace_child_path("../../etc/passwd", ws_root) is False

        # 3. Rejeição de caminhos absolutos fora do workspace
        assert is_safe_workspace_child_path("C:\\Windows\\System32\\cmd.exe", ws_root) is False
        assert is_safe_workspace_child_path("C:\\Program Files", ws_root) is False
        assert is_safe_workspace_child_path("/etc/shadow", ws_root) is False


if __name__ == "__main__":
    print("Executando test_models_and_enums_validation...")
    test_models_and_enums_validation()
    print("Executando test_atomic_storage_and_defaults...")
    test_atomic_storage_and_defaults()
    print("Executando test_corrupted_file_recovery_and_preservation...")
    test_corrupted_file_recovery_and_preservation()
    print("Executando test_squad_export_and_import...")
    test_squad_export_and_import()
    print("Executando test_safe_workspace_child_path_security...")
    test_safe_workspace_child_path_security()
    print("\nTODOS OS TESTES DA ETAPA 1 (MODELOS E PERSISTENCIA) PASSARAM COM SUCESSO!")
