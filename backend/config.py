"""
AgentOffice 2D - Configuration and Constants
"""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
WORKSPACE_FILE = DATA_DIR / "workspace.json"
WORKFLOWS_FILE = DATA_DIR / "workflows.json"
SQUADS_FILE = DATA_DIR / "squads.json"
TASKS_FILE = DATA_DIR / "tasks.json"
BACKUP_DIR = DATA_DIR / "backups"
FRONTEND_DIR = BASE_DIR / "frontend"

# Server configuration (Security: bind only to localhost)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
ALLOWED_HOSTS = {"127.0.0.1", "localhost", f"127.0.0.1:{DEFAULT_PORT}", f"localhost:{DEFAULT_PORT}"}

# Supported LLM Providers
SUPPORTED_PROVIDERS = [
    {"id": "ollama", "name": "Ollama (Local / Offline)", "default_url": "http://localhost:11434", "requires_key": False},
    {"id": "openai_compatible", "name": "vLLM / LM Studio / LocalAI (OpenAI-Compat)", "default_url": "http://localhost:1234/v1", "requires_key": False},
    {"id": "openai", "name": "OpenAI (GPT-4o, o1, o3)", "default_url": "https://api.openai.com/v1", "requires_key": True},
    {"id": "anthropic", "name": "Anthropic Claude (3.5 Sonnet / Haiku)", "default_url": "https://api.anthropic.com", "requires_key": True},
    {"id": "gemini", "name": "Google Gemini (1.5 Flash / Pro, 2.0)", "default_url": "https://generativelanguage.googleapis.com", "requires_key": True},
    {"id": "groq", "name": "Groq (Llama 3.3 Ultra-Fast)", "default_url": "https://api.groq.com/openai/v1", "requires_key": True},
    {"id": "deepseek", "name": "DeepSeek API (V3, R1 Reasoning)", "default_url": "https://api.deepseek.com", "requires_key": True},
    {"id": "mistral", "name": "Mistral AI (Large, Codestral)", "default_url": "https://api.mistral.ai/v1", "requires_key": True},
    {"id": "together", "name": "Together AI / Fireworks / Perplexity", "default_url": "https://api.together.xyz/v1", "requires_key": True},
    {"id": "openrouter", "name": "OpenRouter (Multi-Model Gateway)", "default_url": "https://openrouter.ai/api/v1", "requires_key": True},
    {"id": "custom", "name": "Custom / Corporate Endpoint", "default_url": "http://localhost:8000/v1", "requires_key": False},
]

# Default data templates
DEFAULT_CONFIG = {
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "llama3:latest",
    "api_keys": {},
    "workspace_dir": str(BASE_DIR),
    "ui_preferences": {
        "theme": "retro-dark",
        "sound_enabled": True,
        "pixel_scale": 2
    },
    "configured": False
}

DEFAULT_WORKSPACE = {
    "version": "2.0",
    "agents": [
        {
            "id": "agent-sudo",
            "name": "Pax (@aiox-master)",
            "title": "Master Orchestrator & Diretor Geral",
            "tier": "sudo",
            "avatar_id": "avatar_1",
            "role_type": "solo",
            "supervisor_id": None,
            "subordinate_ids": ["agent-1c137c", "agent-ce2916", "agent-doc"],
            "squad_id": None,
            "desk_id": "desk-sudo",
            "room_id": "room_sudo",
            "system_prompt": "Você é Pax (@aiox-master), o Master Orchestrator e Diretor Geral do ecossistema AIOX Core. Sua responsabilidade é a governança ágil executiva (Agentic Agile), orquestração macro, despacho de épicos e validação final de conformidade.",
            "model_name": "",
            "state": "idle",
            "mission": None,
            "is_temporary": False,
            "aiox_handle": "@aiox-master",
            "aiox_role": "master"
        },
        {
            "id": "agent-1c137c",
            "name": "Aria (@architect)",
            "title": "Software Architect & Tech Lead",
            "tier": "squad_leader",
            "avatar_id": "avatar_3",
            "role_type": "supervisor",
            "supervisor_id": "agent-sudo",
            "subordinate_ids": ["agent-9debfa", "agent-sm"],
            "squad_id": "squad-core-engineering",
            "desk_id": "desk-1",
            "room_id": "room_dev",
            "system_prompt": "Você é Aria (@architect), a Arquiteta de Software Chefe do AIOX Core. Especialista em design de sistemas distribuídos, modelagem de banco de dados SQLite/PostgreSQL, contratos de API FastAPI e governança de Decisões Arquiteturais Registradas (ADRs).",
            "model_name": "",
            "state": "idle",
            "mission": None,
            "is_temporary": False,
            "aiox_handle": "@architect",
            "aiox_role": "architect"
        },
        {
            "id": "agent-9debfa",
            "name": "Dex (@dev)",
            "title": "Senior Software Engineer",
            "tier": "worker",
            "avatar_id": "avatar_1",
            "role_type": "worker",
            "supervisor_id": "agent-1c137c",
            "subordinate_ids": [],
            "squad_id": "squad-core-engineering",
            "desk_id": "desk-2",
            "room_id": "room_dev",
            "system_prompt": "Você é Dex (@dev), o Engenheiro de Software Fullstack do AIOX Core. Especialista em Python 3.10+, FastAPI assíncrono, SQLAlchemy e SQLite. Sua responsabilidade é implementar código estritamente dentro do sandbox de acordo com as especificações da história.",
            "model_name": "",
            "state": "idle",
            "mission": None,
            "is_temporary": False,
            "aiox_handle": "@dev",
            "aiox_role": "dev"
        },
        {
            "id": "agent-sm",
            "name": "Morgan (@sm)",
            "title": "Scrum Master & Agile Planner",
            "tier": "worker",
            "avatar_id": "avatar_2",
            "role_type": "worker",
            "supervisor_id": "agent-1c137c",
            "subordinate_ids": [],
            "squad_id": "squad-core-engineering",
            "desk_id": "desk-3",
            "room_id": "room_dev",
            "system_prompt": "Você é Morgan (@sm), o Scrum Master e Agilista do AIOX Core. Sua responsabilidade é formular Histórias de Usuário completas (STORY-<id>.md), definir critérios de aceitação rigorosos (Acceptance Criteria) e garantir o cumprimento da Definition of Done (DoD).",
            "model_name": "",
            "state": "idle",
            "mission": None,
            "is_temporary": False,
            "aiox_handle": "@sm",
            "aiox_role": "sm"
        },
        {
            "id": "agent-ce2916",
            "name": "Cipher (@sec)",
            "title": "Cybersecurity Director & OWASP Auditor",
            "tier": "squad_leader",
            "avatar_id": "avatar_4",
            "role_type": "solo",
            "supervisor_id": "agent-sudo",
            "subordinate_ids": [],
            "squad_id": "squad-security",
            "desk_id": "desk-sec-1",
            "room_id": "room_sec",
            "system_prompt": "Você é Cipher (@sec), o Auditor Chefe de Cibersegurança do AIOX Core. Especialista em testes de intrusão, proteção contra injeção SQL, integridade do sandbox e conformidade com OWASP.",
            "model_name": "",
            "state": "idle",
            "mission": None,
            "is_temporary": False,
            "aiox_handle": "@sec",
            "aiox_role": "sec"
        },
        {
            "id": "agent-doc",
            "name": "Echo (@doc)",
            "title": "Technical Writer & Documentation Lead",
            "tier": "squad_leader",
            "avatar_id": "avatar_2",
            "role_type": "supervisor",
            "supervisor_id": "agent-sudo",
            "subordinate_ids": ["agent-qa"],
            "squad_id": "squad-documentation",
            "desk_id": "desk-doc-1",
            "room_id": "room_doc",
            "system_prompt": "Você é Echo (@doc), o Líder de Documentação Técnica do AIOX Core. Responsável por especificações OpenAPI, documentação de arquitetura e relatórios executivos.",
            "model_name": "",
            "state": "idle",
            "mission": None,
            "is_temporary": False,
            "aiox_handle": "@doc",
            "aiox_role": "doc"
        },
        {
            "id": "agent-qa",
            "name": "Quinn (@qa)",
            "title": "Quality Guardian & QA Gatekeeper",
            "tier": "worker",
            "avatar_id": "avatar_4",
            "role_type": "worker",
            "supervisor_id": "agent-doc",
            "subordinate_ids": [],
            "squad_id": "squad-documentation",
            "desk_id": "desk-5",
            "room_id": "room_doc",
            "system_prompt": "Você é Quinn (@qa), o Quality Guardian e Auditor de Qualidade do AIOX Core. Sua missão é validar a sintaxe via AST (aiox_validate_code_syntax), executar a auto-crítica ADE (perform_ade_self_critique), verificar a Definition of Done e assinar relatórios QA-REPORT-<id>.md.",
            "model_name": "",
            "state": "idle",
            "mission": None,
            "is_temporary": False,
            "aiox_handle": "@qa",
            "aiox_role": "qa"
        }
    ],
    "desks": [
        {"id": "desk-sudo", "name": "Mesa Diretoria (Pax)", "room_id": "room_sudo", "x": 140, "y": 90, "seat_x": 195, "seat_y": 75, "front_x": 195, "front_y": 165, "width": 110, "height": 55, "agent_id": "agent-sudo"},
        {"id": "desk-1", "name": "Mesa 1 (Aria @architect)", "room_id": "room_dev", "x": 55, "y": 355, "seat_x": 93, "seat_y": 340, "front_x": 93, "front_y": 425, "width": 76, "height": 48, "agent_id": "agent-1c137c"},
        {"id": "desk-2", "name": "Mesa 2 (Dex @dev)", "room_id": "room_dev", "x": 160, "y": 355, "seat_x": 198, "seat_y": 340, "front_x": 198, "front_y": 425, "width": 76, "height": 48, "agent_id": "agent-9debfa"},
        {"id": "desk-3", "name": "Mesa 3 (Morgan @sm)", "room_id": "room_dev", "x": 265, "y": 355, "seat_x": 303, "seat_y": 340, "front_x": 303, "front_y": 425, "width": 76, "height": 48, "agent_id": "agent-sm"},
        {"id": "desk-sec-1", "name": "Mesa Sec (Cipher @sec)", "room_id": "room_sec", "x": 430, "y": 95, "seat_x": 468, "seat_y": 80, "front_x": 468, "front_y": 165, "width": 76, "height": 48, "agent_id": "agent-ce2916"},
        {"id": "desk-sec-2", "name": "Mesa Sec (Auditor)", "room_id": "room_sec", "x": 535, "y": 95, "seat_x": 573, "seat_y": 80, "front_x": 573, "front_y": 165, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-4", "name": "Mesa 4 (SecOps / DevOps)", "room_id": "room_sec", "x": 640, "y": 95, "seat_x": 678, "seat_y": 80, "front_x": 678, "front_y": 165, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-doc-1", "name": "Mesa Doc (Echo @doc)", "room_id": "room_doc", "x": 430, "y": 355, "seat_x": 468, "seat_y": 340, "front_x": 468, "front_y": 425, "width": 76, "height": 48, "agent_id": "agent-doc"},
        {"id": "desk-5", "name": "Mesa 5 (Quinn @qa)", "room_id": "room_doc", "x": 535, "y": 355, "seat_x": 573, "seat_y": 340, "front_x": 573, "front_y": 425, "width": 76, "height": 48, "agent_id": "agent-qa"},
        {"id": "desk-6", "name": "Mesa 6 (UI/UX & Data)", "room_id": "room_doc", "x": 640, "y": 355, "seat_x": 678, "seat_y": 340, "front_x": 678, "front_y": 425, "width": 76, "height": 48, "agent_id": None}
    ],
    "conversations": {},
    "active_tickets": []
}


def is_safe_workspace_path(path_str: str) -> bool:
    """
    Validates if a given path is safe, exists or can be accessed,
    and prevents dangerous paths or traversal attempts.
    """
    if not path_str or not isinstance(path_str, str):
        return False
    try:
        target = Path(path_str).resolve()
        # Ensure it's not a root drive root alone or critical system folder
        if target == target.anchor:
            return False
        # Windows system folder checks
        target_str = str(target).lower()
        if "c:\\windows" in target_str or "c:\\program files" in target_str:
            return False
        return target.exists() and target.is_dir()
    except Exception:
        return False


def is_safe_workspace_child_path(child_path_str: str, workspace_root_str: str) -> bool:
    """
    Ensures that a file or folder path lies strictly within the configured workspace directory.
    Rejects path traversal (..), absolute paths outside the workspace, and escaping symlinks.
    """
    if not child_path_str or not workspace_root_str:
        return False
    try:
        workspace_root = Path(workspace_root_str).resolve()
        candidate = Path(child_path_str)

        if candidate.is_absolute():
            resolved_child = candidate.resolve()
        else:
            resolved_child = (workspace_root / candidate).resolve()

        # Strict containment check
        try:
            resolved_child.relative_to(workspace_root)
        except ValueError:
            return False

        # If it's a symlink, resolve real target and verify containment
        if resolved_child.is_symlink():
            real_target = resolved_child.readlink().resolve()
            try:
                real_target.relative_to(workspace_root)
            except ValueError:
                return False

        return True
    except Exception:
        return False

