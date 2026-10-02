"""
AgentOffice 2D - Storage and Persistence
Provides atomic file operations, backups, and schema validation.
Suporte para config, workspace, squads, workflows e tasks.
"""

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from pydantic import ValidationError

from backend.config import (
    BASE_DIR,
    DATA_DIR,
    CONFIG_FILE,
    WORKSPACE_FILE,
    WORKFLOWS_FILE,
    SQUADS_FILE,
    TASKS_FILE,
    BACKUP_DIR,
    DEFAULT_CONFIG,
    DEFAULT_WORKSPACE,
    SUPPORTED_PROVIDERS,
)
from backend.models import (
    AppConfig,
    ConfigResponse,
    ProviderInfo,
    WorkspaceData,
    Squad,
    SquadExport,
    SquadsData,
    AgentTemplate,
    WorkflowTemplate,
    WorkflowStep,
    WorkflowsData,
    TaskPacket,
    TasksData,
)

logger = logging.getLogger("agentoffice.storage")


class StorageError(Exception):
    """Custom storage exception"""
    pass


# Modelos padrão iniciais da biblioteca
DEFAULT_AGENT_TEMPLATES = [
    {
        "id": "template-aiox-master",
        "name": "Pax (@aiox-master)",
        "title": "Master Orchestrator & Diretor Geral",
        "role_type": "solo",
        "system_prompt": "Você é Pax (@aiox-master), o Master Orchestrator e Diretor Geral do ecossistema AIOX Core. Sua responsabilidade é a governança ágil executiva (Agentic Agile), orquestração macro, despacho de épicos e validação final de conformidade.",
        "avatar_id": "avatar_1",
        "default_model": "",
        "aiox_handle": "@aiox-master",
        "aiox_role": "master"
    },
    {
        "id": "template-architect",
        "name": "Aria (@architect)",
        "title": "Software Architect & Tech Lead",
        "role_type": "supervisor",
        "system_prompt": "Você é Aria (@architect), a Arquiteta de Software Chefe do AIOX Core. Especialista em design de sistemas distribuídos, modelagem de banco de dados SQLite/PostgreSQL, contratos de API FastAPI e governança de Decisões Arquiteturais Registradas (ADRs).",
        "avatar_id": "avatar_3",
        "default_model": "",
        "aiox_handle": "@architect",
        "aiox_role": "architect"
    },
    {
        "id": "template-dev",
        "name": "Dex (@dev)",
        "title": "Senior Software Engineer",
        "role_type": "worker",
        "system_prompt": "Você é Dex (@dev), o Engenheiro de Software Fullstack do AIOX Core. Especialista em Python 3.10+, FastAPI assíncrono, SQLAlchemy e SQLite. Sua responsabilidade é implementar código estritamente dentro do sandbox de acordo com as especificações da história.",
        "avatar_id": "avatar_1",
        "default_model": "",
        "aiox_handle": "@dev",
        "aiox_role": "dev"
    },
    {
        "id": "template-sm",
        "name": "Morgan (@sm)",
        "title": "Scrum Master & Agile Planner",
        "role_type": "worker",
        "system_prompt": "Você é Morgan (@sm), o Scrum Master e Agilista do AIOX Core. Sua responsabilidade é formular Histórias de Usuário completas (STORY-<id>.md), definir critérios de aceitação rigorosos (Acceptance Criteria) e garantir o cumprimento da Definition of Done (DoD).",
        "avatar_id": "avatar_2",
        "default_model": "",
        "aiox_handle": "@sm",
        "aiox_role": "sm"
    },
    {
        "id": "template-qa",
        "name": "Quinn (@qa)",
        "title": "Quality Guardian & QA Gatekeeper",
        "role_type": "worker",
        "system_prompt": "Você é Quinn (@qa), o Quality Guardian e Auditor de Qualidade do AIOX Core. Sua missão é validar a sintaxe via AST (aiox_validate_code_syntax), executar a auto-crítica ADE (perform_ade_self_critique), verificar a Definition of Done e assinar relatórios QA-REPORT-<id>.md.",
        "avatar_id": "avatar_4",
        "default_model": "",
        "aiox_handle": "@qa",
        "aiox_role": "qa"
    },
    {
        "id": "template-sec",
        "name": "Cipher (@sec)",
        "title": "Cybersecurity Director & OWASP Auditor",
        "role_type": "solo",
        "system_prompt": "Você é Cipher (@sec), o Auditor Chefe de Cibersegurança do AIOX Core. Especialista em testes de intrusão, proteção contra injeção SQL, integridade do sandbox e conformidade com OWASP.",
        "avatar_id": "avatar_4",
        "default_model": "",
        "aiox_handle": "@sec",
        "aiox_role": "sec"
    },
    {
        "id": "template-doc",
        "name": "Echo (@doc)",
        "title": "Technical Writer & Documentation Lead",
        "role_type": "supervisor",
        "system_prompt": "Você é Echo (@doc), o Líder de Documentação Técnica do AIOX Core. Responsável por especificações OpenAPI, documentação de arquitetura e relatórios executivos.",
        "avatar_id": "avatar_2",
        "default_model": "",
        "aiox_handle": "@doc",
        "aiox_role": "doc"
    }
]

DEFAULT_SQUADS = [
    {
        "id": "squad-core-engineering",
        "name": "Squad Core Engineering",
        "room_id": "room_dev",
        "leader_id": "agent-dev-leader",
        "member_ids": ["agent-dev-leader", "agent-dev-backend", "agent-dev-frontend"],
        "agent_ids": ["template-tech-lead", "template-python-dev", "template-qa"],
        "domain_tags": ["python", "api", "database", "fastapi", "sqlite", "frontend"],
        "color_theme": "#10b981",
        "description": "Equipe multifuncional de engenharia para desenvolvimento, revisão e arquitetura.",
        "created_at": 1700000000.0
    },
    {
        "id": "squad-security",
        "name": "Squad Cyber Security",
        "room_id": "room_sec",
        "leader_id": "agent-sec-leader",
        "member_ids": ["agent-sec-leader", "agent-sec-auditor"],
        "agent_ids": ["agent-sec-leader", "agent-sec-auditor"],
        "domain_tags": ["security", "audit", "crypto", "hardening", "vulnerabilities"],
        "color_theme": "#a855f7",
        "description": "Auditoria de segurança, análise de vulnerabilidades, sanitização e conformidade.",
        "created_at": 1700000000.0
    },
    {
        "id": "squad-documentation",
        "name": "Squad Documentação & QA",
        "room_id": "room_doc",
        "leader_id": "agent-doc-leader",
        "member_ids": ["agent-doc-leader", "agent-doc-writer"],
        "agent_ids": ["agent-doc-leader", "agent-doc-writer"],
        "domain_tags": ["documentation", "qa", "specs", "manuals", "markdown", "design"],
        "color_theme": "#f59e0b",
        "description": "Documentação técnica, especificações de endpoints e manuais de arquitetura.",
        "created_at": 1700000000.0
    }
]

DEFAULT_WORKFLOWS = [
    {
        "id": "workflow-standard-engineering",
        "name": "Workflow Padrão de Engenharia",
        "description": "Ciclo completo de engenharia: Planejamento, Execução, Revisão por QA e Relatório Final.",
        "steps": [
            {
                "id": "step-planning",
                "name": "Planejamento Arquitetural",
                "required_role": "supervisor",
                "action_type": "generate",
                "instructions": "Analise a solicitação do usuário, avalie o escopo e gere o plano de arquitetura e execução detalhado.",
                "requires_human_approval": False,
                "max_revisions": 2
            },
            {
                "id": "step-execution",
                "name": "Execução & Proposta de Código",
                "required_role": "worker",
                "action_type": "prepare_change",
                "instructions": "Implemente a solução conforme o plano definido e prepare os artefatos de código e propostas de alteração.",
                "requires_human_approval": True,
                "max_revisions": 2
            },
            {
                "id": "step-qa-review",
                "name": "Revisão de Qualidade & Testes",
                "required_role": "worker",
                "action_type": "review",
                "instructions": "Inspecione minuciosamente os artefatos gerados, verifique a segurança, boas práticas e ausência de regressões.",
                "review_criteria": [
                    "Código limpo, seguro e com tipagem",
                    "Sem vulnerabilidades ou escape de diretório",
                    "Atende aos objetivos da tarefa"
                ],
                "requires_human_approval": False,
                "max_revisions": 2
            },
            {
                "id": "step-final-report",
                "name": "Relatório Final & Conclusão",
                "required_role": "supervisor",
                "action_type": "generate",
                "instructions": "Consolide a entrega, resuma as decisões tomadas, evidências de testes e finalize o relatório do workflow.",
                "requires_human_approval": False,
                "max_revisions": 2
            }
        ]
    }
]


class Storage:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.config_file = self.data_dir / "config.json"
        self.workspace_file = self.data_dir / "workspace.json"
        self.squads_file = self.data_dir / "squads.json"
        self.workflows_file = self.data_dir / "workflows.json"
        self.tasks_file = self.data_dir / "tasks.json"
        self.backup_dir = self.data_dir / "backups"
        self.ensure_directories()

    def ensure_directories(self) -> None:
        """Create data and backup directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write_json(self, file_path: Path, data: Dict[str, Any]) -> None:
        """
        Writes data to a temporary file in the same directory, flushes,
        fsyncs and performs an atomic replace to prevent corrupted files.
        """
        parent_dir = file_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        temp_fd, temp_path = tempfile.mkstemp(
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            dir=parent_dir
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, file_path)
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            logger.error(f"Falha ao salvar arquivo atomicamente {file_path}: {e}")
            raise StorageError(f"Erro ao salvar arquivo {file_path.name}: {e}") from e

    def _create_backup(self, file_path: Path, prefix: str) -> None:
        """Creates a timestamped backup before altering a file."""
        if not file_path.exists():
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{prefix}_{timestamp}.bak"
        try:
            shutil.copy2(file_path, backup_path)
            # Prune old backups, keeping latest 10
            backups = sorted(self.backup_dir.glob(f"{prefix}_*.bak"))
            if len(backups) > 10:
                for old in backups[:-10]:
                    try:
                        old.unlink()
                    except OSError:
                        pass
        except Exception as e:
            logger.warning(f"Não foi possível criar backup de {file_path}: {e}")

    def ensure_initial_data(self) -> None:
        """
        Ensures initial config.json, workspace.json, squads.json,
        workflows.json, and tasks.json exist.
        """
        self.ensure_directories()

        # Initialize config.json
        if not self.config_file.exists():
            logger.info("Criando data/config.json padrão...")
            config_data = dict(DEFAULT_CONFIG)
            config_data["workspace_dir"] = str(BASE_DIR)
            self._atomic_write_json(self.config_file, config_data)

        # Initialize workspace.json
        if not self.workspace_file.exists():
            logger.info("Criando data/workspace.json padrão...")
            self._atomic_write_json(self.workspace_file, DEFAULT_WORKSPACE)

        # Initialize squads.json
        if not self.squads_file.exists():
            logger.info("Criando data/squads.json padrão com templates...")
            initial_squads = {
                "templates": DEFAULT_AGENT_TEMPLATES,
                "squads": DEFAULT_SQUADS
            }
            self._atomic_write_json(self.squads_file, initial_squads)

        # Initialize workflows.json
        if not self.workflows_file.exists():
            logger.info("Criando data/workflows.json padrão...")
            initial_workflows = {
                "workflows": DEFAULT_WORKFLOWS
            }
            self._atomic_write_json(self.workflows_file, initial_workflows)

        # Initialize tasks.json
        if not self.tasks_file.exists():
            logger.info("Criando data/tasks.json padrão...")
            initial_tasks = {
                "tasks": []
            }
            self._atomic_write_json(self.tasks_file, initial_tasks)

    # --- Config ---

    def load_config(self) -> AppConfig:
        self.ensure_initial_data()
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            return AppConfig(**raw_data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Arquivo config.json inválido ou corrompido: {e}")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            corrupt_copy = self.data_dir / f"config.json.corrupt.{timestamp}"
            shutil.copy2(self.config_file, corrupt_copy)
            logger.warning(f"Cópia do arquivo corrompido salva em: {corrupt_copy}")

            default_config = AppConfig(**DEFAULT_CONFIG)
            default_config.workspace_dir = str(BASE_DIR)
            self.save_config(default_config, backup=False)
            return default_config
        except Exception as e:
            raise StorageError(f"Erro ao carregar configurações: {e}")

    def save_config(self, config: AppConfig, backup: bool = True) -> AppConfig:
        if backup and self.config_file.exists():
            self._create_backup(self.config_file, "config")
        self._atomic_write_json(self.config_file, config.model_dump())
        return config

    def get_safe_config_view(self, config: AppConfig) -> ConfigResponse:
        has_keys = {
            provider["id"]: bool(config.api_keys.get(provider["id"]))
            for provider in SUPPORTED_PROVIDERS
        }

        providers = [
            ProviderInfo(
                id=p["id"],
                name=p["name"],
                default_url=p["default_url"],
                requires_key=p["requires_key"]
            )
            for p in SUPPORTED_PROVIDERS
        ]

        return ConfigResponse(
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            has_api_keys=has_keys,
            workspace_dir=config.workspace_dir,
            ui_preferences=config.ui_preferences,
            configured=config.configured,
            supported_providers=providers
        )

    # --- Workspace ---

    def load_workspace(self) -> WorkspaceData:
        self.ensure_initial_data()
        try:
            with open(self.workspace_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            desks = raw_data.get("desks", [])
            needs_save = False
            default_desks = {d["id"]: d for d in DEFAULT_WORKSPACE["desks"]}

            for desk in desks:
                d_id = desk.get("id")
                if "seat_x" not in desk and d_id in default_desks:
                    def_d = default_desks[d_id]
                    desk["seat_x"] = def_d["seat_x"]
                    desk["seat_y"] = def_d["seat_y"]
                    desk["front_x"] = def_d["front_x"]
                    desk["front_y"] = def_d["front_y"]
                    desk["width"] = def_d.get("width", 76)
                    desk["height"] = def_d.get("height", 48)
                    needs_save = True

            workspace = WorkspaceData(**raw_data)
            if needs_save:
                self.save_workspace(workspace, backup=False)
            return workspace
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Arquivo workspace.json inválido: {e}")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            corrupt_copy = self.data_dir / f"workspace.json.corrupt.{timestamp}"
            shutil.copy2(self.workspace_file, corrupt_copy)
            default_workspace = WorkspaceData(**DEFAULT_WORKSPACE)
            self.save_workspace(default_workspace, backup=False)
            return default_workspace

    def save_workspace(self, workspace: WorkspaceData, backup: bool = True) -> WorkspaceData:
        if backup and self.workspace_file.exists():
            self._create_backup(self.workspace_file, "workspace")
        self._atomic_write_json(self.workspace_file, workspace.model_dump())
        return workspace

    # --- Squads e Templates ---

    def load_squads(self) -> SquadsData:
        self.ensure_initial_data()
        try:
            with open(self.squads_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            return SquadsData(**raw_data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Arquivo squads.json inválido ou corrompido: {e}")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            corrupt_copy = self.data_dir / f"squads.json.corrupt.{timestamp}"
            shutil.copy2(self.squads_file, corrupt_copy)
            logger.warning(f"Cópia do squads.json corrompido salva em: {corrupt_copy}")

            default_squads = SquadsData(
                templates=[AgentTemplate(**t) for t in DEFAULT_AGENT_TEMPLATES],
                squads=[Squad(**s) for s in DEFAULT_SQUADS]
            )
            self.save_squads(default_squads, backup=False)
            return default_squads

    def save_squads(self, data: SquadsData, backup: bool = True) -> SquadsData:
        if backup and self.squads_file.exists():
            self._create_backup(self.squads_file, "squads")
        self._atomic_write_json(self.squads_file, data.model_dump())
        return data

    def export_squad(self, squad_id: str) -> SquadExport:
        """Exporta um squad e seus templates de agentes associados sem nenhuma chave de API ou segredo."""
        squads_data = self.load_squads()
        squad = next((s for s in squads_data.squads if s.id == squad_id), None)
        if not squad:
            raise StorageError(f"Squad '{squad_id}' não encontrado para exportação.")

        # Coletar os templates dos agentes do squad
        template_map = {t.id: t for t in squads_data.templates}
        templates = [template_map[aid] for aid in squad.agent_ids if aid in template_map]

        return SquadExport(
            version="1.0",
            squad=squad,
            agent_templates=templates
        )

    def import_squad(self, export_data: SquadExport) -> Squad:
        """Importa um squad validado e seus templates sem sobrescrever ou permitir injeção de segredos."""
        squads_data = self.load_squads()

        # Adicionar templates que não existam ainda
        existing_template_ids = {t.id for t in squads_data.templates}
        for tmpl in export_data.agent_templates:
            if tmpl.id not in existing_template_ids:
                squads_data.templates.append(tmpl)
                existing_template_ids.add(tmpl.id)

        # Adicionar ou atualizar squad
        existing_squad = next((s for s in squads_data.squads if s.id == export_data.squad.id), None)
        if existing_squad:
            squads_data.squads = [
                export_data.squad if s.id == export_data.squad.id else s
                for s in squads_data.squads
            ]
        else:
            squads_data.squads.append(export_data.squad)

        self.save_squads(squads_data, backup=True)
        return export_data.squad

    # --- Workflows ---

    def load_workflows(self) -> WorkflowsData:
        self.ensure_initial_data()
        try:
            with open(self.workflows_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            return WorkflowsData(**raw_data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Arquivo workflows.json inválido ou corrompido: {e}")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            corrupt_copy = self.data_dir / f"workflows.json.corrupt.{timestamp}"
            shutil.copy2(self.workflows_file, corrupt_copy)
            logger.warning(f"Cópia do workflows.json corrompido salva em: {corrupt_copy}")

            default_workflows = WorkflowsData(
                workflows=[WorkflowTemplate(**w) for w in DEFAULT_WORKFLOWS]
            )
            self.save_workflows(default_workflows, backup=False)
            return default_workflows

    def save_workflows(self, data: WorkflowsData, backup: bool = True) -> WorkflowsData:
        if backup and self.workflows_file.exists():
            self._create_backup(self.workflows_file, "workflows")
        self._atomic_write_json(self.workflows_file, data.model_dump())
        return data

    # --- Tasks ---

    def load_tasks(self) -> TasksData:
        self.ensure_initial_data()
        try:
            with open(self.tasks_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            return TasksData(**raw_data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Arquivo tasks.json inválido ou corrompido: {e}")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            corrupt_copy = self.data_dir / f"tasks.json.corrupt.{timestamp}"
            shutil.copy2(self.tasks_file, corrupt_copy)
            logger.warning(f"Cópia do tasks.json corrompido salva em: {corrupt_copy}")

            empty_tasks = TasksData(tasks=[])
            self.save_tasks(empty_tasks, backup=False)
            return empty_tasks

    def save_tasks(self, data: TasksData, backup: bool = True) -> TasksData:
        if backup and self.tasks_file.exists():
            self._create_backup(self.tasks_file, "tasks")
        self._atomic_write_json(self.tasks_file, data.model_dump())
        return data


# Instância global singleton
storage = Storage()
