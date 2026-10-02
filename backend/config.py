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
    "agents": [],
    "desks": [
        {"id": "desk-sudo", "name": "Mesa Diretoria (Sudo)", "room_id": "room_sudo", "x": 140, "y": 90, "seat_x": 195, "seat_y": 75, "front_x": 195, "front_y": 165, "width": 110, "height": 55, "agent_id": None},
        {"id": "desk-1", "name": "Mesa 1 (Líder Dev)", "room_id": "room_dev", "x": 55, "y": 355, "seat_x": 93, "seat_y": 340, "front_x": 93, "front_y": 425, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-2", "name": "Mesa 2 (Dev Backend)", "room_id": "room_dev", "x": 160, "y": 355, "seat_x": 198, "seat_y": 340, "front_x": 198, "front_y": 425, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-3", "name": "Mesa 3 (Dev Frontend)", "room_id": "room_dev", "x": 265, "y": 355, "seat_x": 303, "seat_y": 340, "front_x": 303, "front_y": 425, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-sec-1", "name": "Mesa Sec (Líder)", "room_id": "room_sec", "x": 430, "y": 95, "seat_x": 468, "seat_y": 80, "front_x": 468, "front_y": 165, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-sec-2", "name": "Mesa Sec (Auditor)", "room_id": "room_sec", "x": 535, "y": 95, "seat_x": 573, "seat_y": 80, "front_x": 573, "front_y": 165, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-4", "name": "Mesa 4 (SecOps / DevOps)", "room_id": "room_sec", "x": 640, "y": 95, "seat_x": 678, "seat_y": 80, "front_x": 678, "front_y": 165, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-doc-1", "name": "Mesa Doc (Líder)", "room_id": "room_doc", "x": 430, "y": 355, "seat_x": 468, "seat_y": 340, "front_x": 468, "front_y": 425, "width": 76, "height": 48, "agent_id": None},
        {"id": "desk-5", "name": "Mesa 5 (Tech Writer & QA)", "room_id": "room_doc", "x": 535, "y": 355, "seat_x": 573, "seat_y": 340, "front_x": 573, "front_y": 425, "width": 76, "height": 48, "agent_id": None},
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

