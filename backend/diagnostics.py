"""
AgentOffice 2D - System Diagnostics Engine
Realiza verificações de integridade em tempo real:
- Conexão e latência do provedor de LLM (Ollama / Local / Nuvem)
- Autenticação e chaves de API
- Permissões de Leitura/Escrita do Workspace Sandbox
- Integridade estrutural dos arquivos JSON de persistência
- Informações de ambiente e recursos do servidor local
"""

import logging
import os
import platform
import sys
import time
from pathlib import Path
from typing import Dict, Any

import httpx

from backend.config import (
    BASE_DIR,
    DATA_DIR,
    CONFIG_FILE,
    WORKSPACE_FILE,
    WORKFLOWS_FILE,
    SQUADS_FILE,
    TASKS_FILE,
    SUPPORTED_PROVIDERS,
)
from backend.llm_gateway import LLMGatewayFactory
from backend.models import DiagnosticItem, DiagnosticResult
from backend.storage import storage

logger = logging.getLogger("agentoffice.diagnostics")


async def run_system_diagnostics() -> DiagnosticResult:
    """
    Executa bateria completa de diagnósticos do sistema AgentOffice 2D.
    Não vaza chaves secretas ou credenciais confidenciais.
    """
    items = []
    has_error = False
    has_warning = False

    config = storage.load_config()

    # 1. Diagnóstico do Provedor LLM / Multi-Provedor Gateway
    t0 = time.perf_counter()
    llm_status = "healthy"
    llm_msg = ""
    llm_latency = 0.0
    llm_details: Dict[str, Any] = {
        "provider": config.provider,
        "base_url": config.base_url,
        "selected_model": config.model
    }

    try:
        adapter = LLMGatewayFactory.from_config(config)
        test_res = await adapter.test_connection(timeout=3.0)
        llm_latency = test_res.get("latency_ms") or round((time.perf_counter() - t0) * 1000, 1)
        models = test_res.get("models", [])
        llm_details["models_detected"] = len(models)
        llm_details["sample_models"] = models[:5]

        if test_res.get("success"):
            llm_msg = test_res.get("message", "Conectado com sucesso")
            llm_status = "healthy"
        else:
            llm_status = "warning"
            has_warning = True
            llm_msg = test_res.get("message") or f"Não foi possível conectar ao provedor {config.provider}"
            if test_res.get("details"):
                llm_details["error_details"] = test_res.get("details")
    except Exception as e:
        llm_latency = round((time.perf_counter() - t0) * 1000, 1)
        llm_status = "warning"
        has_warning = True
        llm_msg = f"Aviso de conexão com o provedor: {str(e)[:120]}"

    items.append(DiagnosticItem(
        name="Provedor LLM & IA Local",
        status=llm_status,
        message=llm_msg,
        latency_ms=llm_latency,
        details=llm_details
    ))

    # 2. Diagnóstico de Chaves de API e Configuração
    provider_meta = next((p for p in SUPPORTED_PROVIDERS if p["id"] == config.provider), None)
    key_status = "healthy"
    key_msg = ""

    if provider_meta and provider_meta.get("requires_key"):
        has_key = bool(config.api_keys.get(config.provider))
        if has_key:
            key_msg = f"Chave de API configurada para o provedor '{provider_meta['name']}'."
        else:
            key_status = "warning"
            has_warning = True
            key_msg = f"Chave de API ausente para '{provider_meta['name']}'. Configure no menu de Configurações."
    else:
        key_msg = f"Provedor '{config.provider}' opera localmente sem necessidade de chave de API."

    items.append(DiagnosticItem(
        name="Autenticação & Chaves",
        status=key_status,
        message=key_msg,
        details={"requires_key": provider_meta.get("requires_key", False) if provider_meta else False}
    ))

    # 3. Diagnóstico do Diretório de Workspace (Sandbox I/O)
    ws_t0 = time.perf_counter()
    ws_status = "healthy"
    ws_msg = ""
    target_ws = config.workspace_dir or str(BASE_DIR)
    ws_latency = 0.0

    try:
        ws_path = Path(target_ws).resolve()
        if not ws_path.exists():
            ws_status = "error"
            has_error = True
            ws_msg = f"Diretório de workspace não existe: {target_ws}"
        else:
            test_file = ws_path / f".agentoffice_diag_test_{os.getpid()}.tmp"
            test_file.write_text("agentoffice-diagnostics-test", encoding="utf-8")
            read_back = test_file.read_text(encoding="utf-8")
            test_file.unlink(missing_ok=True)

            if read_back != "agentoffice-diagnostics-test":
                ws_status = "error"
                has_error = True
                ws_msg = "Falha na verificação de integridade de leitura no workspace."
            else:
                ws_latency = round((time.perf_counter() - ws_t0) * 1000, 2)
                ws_msg = f"Permissões de Leitura e Escrita confirmadas ({ws_path.name})"
    except Exception as e:
        ws_status = "error"
        has_error = True
        ws_msg = f"Erro de I/O no workspace: {str(e)[:120]}"

    items.append(DiagnosticItem(
        name="Workspace Sandbox & I/O",
        status=ws_status,
        message=ws_msg,
        latency_ms=ws_latency,
        details={"workspace_dir": str(target_ws)}
    ))

    # 4. Diagnóstico de Integridade dos Arquivos de Dados
    storage_status = "healthy"
    storage_details: Dict[str, Any] = {}
    storage_errors = []

    files_to_check = [
        ("config.json", CONFIG_FILE, storage.load_config),
        ("workspace.json", WORKSPACE_FILE, storage.load_workspace),
        ("workflows.json", WORKFLOWS_FILE, storage.load_workflows),
        ("squads.json", SQUADS_FILE, storage.load_squads),
        ("tasks.json", TASKS_FILE, storage.load_tasks),
    ]

    for fname, fpath, loader in files_to_check:
        try:
            loaded = loader()
            storage_details[fname] = {
                "exists": fpath.exists(),
                "size_bytes": fpath.stat().st_size if fpath.exists() else 0,
                "status": "valid"
            }
        except Exception as e:
            storage_errors.append(f"{fname}: {str(e)[:80]}")
            storage_details[fname] = {"exists": fpath.exists(), "status": "corrupt", "error": str(e)}

    if storage_errors:
        storage_status = "error"
        has_error = True
        storage_msg = f"{len(storage_errors)} arquivo(s) com erro: " + "; ".join(storage_errors)
    else:
        # Contagem de entidades
        ws_data = storage.load_workspace()
        tasks_data = storage.load_tasks()
        squads_data = storage.load_squads()
        workflows_data = storage.load_workflows()

        storage_msg = (
            f"Todos os 5 arquivos íntegros "
            f"({len(ws_data.agents)} agentes, {len(workflows_data.workflows)} workflows, "
            f"{len(squads_data.squads)} squads, {len(tasks_data.tasks)} tarefas)"
        )

    items.append(DiagnosticItem(
        name="Persistência & Integridade JSON",
        status=storage_status,
        message=storage_msg,
        details=storage_details
    ))

    # 5. Informações do Ambiente e Recursos
    system_info = {
        "os": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "process_pid": os.getpid(),
        "data_dir": str(DATA_DIR),
        "server_host": "127.0.0.1:8000"
    }

    # Definir status geral consolidado
    if has_error:
        overall = "error"
    elif has_warning:
        overall = "warning"
    else:
        overall = "healthy"

    return DiagnosticResult(
        overall_status=overall,
        timestamp=time.time(),
        items=items,
        system_info=system_info
    )
