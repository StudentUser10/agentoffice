"""
AgentOffice 2D - FastAPI Server
Handles configuration, provider detection, connection testing, and security.
"""

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import (
    ALLOWED_HOSTS,
    BASE_DIR,
    FRONTEND_DIR,
    SUPPORTED_PROVIDERS,
    is_safe_workspace_path,
)
from backend.models import (
    Agent,
    AgentCreateRequest,
    AgentRoleType,
    AgentTier,
    AgentTemplate,
    AgentUpdateRequest,
    ApprovalDecisionRequest,
    ApprovalRequest,
    ChatRequest,
    ConfigResponse,
    ConfigUpdateRequest,
    CrossSquadTicket,
    DetectModelsResponse,
    DiagnosticItem,
    DiagnosticResult,
    DirectorySelectResponse,
    Squad,
    SquadCreateRequest,
    SquadExport,
    SquadUpdateRequest,
    SquadsData,
    TaskCreateRequest,
    TaskPacket,
    TasksData,
    TaskState,
    TaskUpdateRequest,
    TestConnectionRequest,
    TestConnectionResponse,
    WorkflowCreateRequest,
    WorkflowStep,
    WorkflowTemplate,
    WorkflowUpdateRequest,
    WorkflowsData,
    WorkspaceData,
)
from backend.orchestrator import orchestrator
from backend.orchestrator_multi_tier import multi_tier_orchestrator
from backend.tools.squad_tools import resolve_cross_squad_ticket
import yaml
from backend.memory_layer import memory_layer
from backend.diagnostics import run_system_diagnostics
from backend.storage import storage
from backend.websocket_hub import hub
from backend.llm_gateway import LLMGatewayFactory
from backend.workflow_engine import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    InvalidTransitionError,
    SecurityPathError,
    TaskAlreadyRunningError,
    workflow_engine,
)

# Configure logging (no sensitive data)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("agentoffice.app")

app = FastAPI(
    title="AgentOffice 2D",
    description="Interface de escritório em pixel art para agentes de IA",
    version="0.1.0"
)

# CORS restricted strictly to localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://localhost",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_host_and_origin_middleware(request: Request, call_next):
    """
    Validates Host and Origin headers to protect against DNS rebinding and cross-origin attacks.
    """
    # Verify Host
    host_header = request.headers.get("host", "")
    host_name = host_header.split(":")[0].strip().lower()
    if host_name and host_name not in ("127.0.0.1", "localhost", "testserver"):
        logger.warning(f"Tentativa de acesso com Host inválido: {host_name}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "Acesso não autorizado: Host não permitido."}
        )

    # Verify Origin for mutating requests
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin:
            origin_clean = origin.replace("http://", "").replace("https://", "").split(":")[0]
            if origin_clean not in ("127.0.0.1", "localhost"):
                logger.warning(f"Tentativa de alteração com Origin inválida: {origin}")
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": "Acesso não autorizado: Origem não permitida."}
                )

    response = await call_next(request)
    return response


# --- Static Files and Frontend ---
if not FRONTEND_DIR.exists():
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files directory if subdirectories exist
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serves the main frontend single-page application."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo frontend/index.html não encontrado."
        )
    return FileResponse(index_file)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "app": "AgentOffice 2D", "version": "0.1.0"}


# --- Configuration Endpoints ---

@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """
    Returns non-secret configuration and indicator of configured API keys.
    API keys are NEVER sent to the client.
    """
    config = storage.load_config()
    return storage.get_safe_config_view(config)


@app.post("/api/config", response_model=ConfigResponse)
async def update_config(update: ConfigUpdateRequest):
    """
    Updates application configuration.
    Stores API keys securely and returns sanitized view without revealing saved values.
    """
    config = storage.load_config()

    if update.provider is not None:
        valid_ids = {p["id"] for p in SUPPORTED_PROVIDERS}
        if update.provider not in valid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Provedor '{update.provider}' não é suportado."
            )
        config.provider = update.provider

    if update.base_url is not None:
        config.base_url = update.base_url.strip().rstrip("/")

    if update.model is not None:
        config.model = update.model.strip()

    # Handle single key update for current or chosen provider
    if update.api_key is not None:
        key_val = update.api_key.strip()
        if key_val:
            config.api_keys[config.provider] = key_val

    # Handle dictionary of keys
    if update.provider_keys:
        for prov_id, key_val in update.provider_keys.items():
            clean_key = (key_val or "").strip()
            if clean_key:
                config.api_keys[prov_id] = clean_key

    # Handle clearing keys explicitly
    if update.clear_keys:
        for prov_id in update.clear_keys:
            config.api_keys.pop(prov_id, None)

    # Handle workspace directory
    if update.workspace_dir is not None:
        candidate_path = update.workspace_dir.strip()
        if candidate_path:
            # Validate workspace directory
            if not is_safe_workspace_path(candidate_path):
                # Try to create if it doesn't exist yet but parent is valid
                try:
                    p = Path(candidate_path).resolve()
                    if not p.exists():
                        p.mkdir(parents=True, exist_ok=True)
                    config.workspace_dir = str(p)
                except Exception as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Pasta de trabalho inválida ou inacessível: {e}"
                    )
            else:
                config.workspace_dir = str(Path(candidate_path).resolve())

    if update.ui_preferences is not None:
        config.ui_preferences = update.ui_preferences

    if update.configured is not None:
        config.configured = update.configured
    else:
        # Mark as configured once user saves
        config.configured = True

    saved = storage.save_config(config)
    return storage.get_safe_config_view(saved)


@app.post("/api/config/test-connection", response_model=TestConnectionResponse)
async def test_connection(payload: TestConnectionRequest):
    """
    Tests connection to any supported LLM provider using the unified LLM Gateway.
    """
    config = storage.load_config()
    provider = payload.provider
    base_url = (payload.base_url or "").strip().rstrip("/")
    if not base_url and config.provider == provider:
        base_url = config.base_url
    api_key = payload.api_key or config.api_keys.get(provider, "")

    adapter = LLMGatewayFactory.get_adapter(
        provider=provider,
        base_url=base_url or None,
        api_key=api_key or None,
        model=config.model
    )
    result = await adapter.test_connection(timeout=6.0)
    return TestConnectionResponse(
        success=result.get("success", False),
        message=result.get("message", ""),
        models=result.get("models", []),
        details=result.get("details")
    )


@app.get("/api/config/detect-models", response_model=DetectModelsResponse)
async def detect_models():
    """
    Detects available models using the LLM Gateway adapter for the active provider.
    """
    config = storage.load_config()
    adapter = LLMGatewayFactory.from_config(config)
    try:
        models = await adapter.list_models(timeout=3.0)
        if models:
            return DetectModelsResponse(
                available=True,
                models=models,
                message=f"{len(models)} modelo(s) encontrado(s) no {adapter.provider.capitalize()}."
            )
    except Exception:
        pass

    return DetectModelsResponse(
        available=False,
        models=[],
        message=f"{adapter.provider.capitalize()} não está acessível em '{adapter.base_url}'. Certifique-se de que o Ollama está rodando."
    )


def _native_folder_dialog(initial_dir: Optional[str] = None) -> Optional[str]:
    """Helper executed in thread pool to show native Tkinter folder dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(
            initialdir=initial_dir if initial_dir and Path(initial_dir).exists() else None,
            title="Selecione a Pasta de Trabalho do AgentOffice"
        )
        root.destroy()
        return folder if folder else None
    except Exception as e:
        logger.warning(f"Não foi possível abrir o seletor nativo: {e}")
        return None


@app.post("/api/config/select-directory", response_model=DirectorySelectResponse)
async def select_directory():
    """
    Triggers native OS folder picker in a background thread so the event loop is never blocked.
    """
    config = storage.load_config()
    current_dir = config.workspace_dir or str(BASE_DIR)

    folder_path = await asyncio.to_thread(_native_folder_dialog, current_dir)

    if folder_path:
        return DirectorySelectResponse(
            selected=True,
            path=folder_path,
            message="Diretório selecionado com sucesso."
        )
    return DirectorySelectResponse(
        selected=False,
        path=None,
        message="Seleção cancelada pelo usuário ou seletor nativo indisponível."
    )


# --- WebSocket Hub Endpoint ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Canal WebSocket para atualizações em tempo real do escritório e streaming de chat."""
    origin = websocket.headers.get("origin")
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        origin_host = parsed.hostname
        if origin_host and origin_host not in ALLOWED_HOSTS and origin_host not in ("127.0.0.1", "localhost", "testserver"):
            logger.warning(f"Conexão WebSocket rejeitada: Origem não permitida '{origin}'.")
            await websocket.close(code=1008)
            return

    await hub.connect(websocket)
    try:
        # Enviar estado inicial do workspace e tarefas para sincronização imediata
        ws_data = storage.load_workspace()
        import json
        await websocket.send_text(json.dumps({
            "type": "workspace.updated",
            "workspace": ws_data.model_dump()
        }, ensure_ascii=False))

        while True:
            # Mantém conexão aberta e escuta pings/mensagens do cliente
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                msg_type = msg.get("event") or msg.get("type")
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "event": "pong"}))
                elif msg_type == "tasks.sync":
                    current_tasks = storage.load_tasks()
                    await websocket.send_text(json.dumps({
                        "event": "tasks.sync",
                        "type": "tasks.sync",
                        "tasks": [t.model_dump() for t in current_tasks.tasks]
                    }, ensure_ascii=False))
            except Exception:
                pass
    except WebSocketDisconnect:
        hub.disconnect(websocket)
    except Exception as e:
        logger.warning(f"Conexão WebSocket finalizada: {e}")
        hub.disconnect(websocket)


# --- Workspace & Agent CRUD Endpoints ---

@app.get("/api/workspace", response_model=WorkspaceData)
async def get_workspace():
    """Retorna o estado completo das mesas, agentes e conversas."""
    return storage.load_workspace()


@app.post("/api/agents", response_model=Agent)
async def create_agent(req: AgentCreateRequest):
    """Cria um novo agente, vincula a uma mesa e sincroniza hierarquia."""
    workspace = storage.load_workspace()

    # Validar se a mesa existe
    desk = next((d for d in workspace.desks if d.id == req.desk_id), None)
    if not desk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mesa '{req.desk_id}' não encontrada."
        )

    # Validar se a mesa já está ocupada
    if desk.agent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A mesa '{desk.name}' já está ocupada por outro agente."
        )

    agent_id = f"agent-{uuid.uuid4().hex[:6]}"
    config = storage.load_config()

    new_agent = Agent(
        id=agent_id,
        name=req.name.strip(),
        title=req.title.strip() or "Assistente",
        tier=getattr(req, "tier", None) or AgentTier.WORKER,
        avatar_id=req.avatar_id or "avatar_1",
        role_type=req.role_type,
        supervisor_id=req.supervisor_id if req.role_type == AgentRoleType.WORKER else None,
        subordinate_ids=[],
        squad_id=getattr(req, "squad_id", None),
        desk_id=req.desk_id,
        room_id=getattr(desk, "room_id", "room_dev"),
        system_prompt=req.system_prompt or "Você é um assistente técnico inteligente.",
        model_name=(req.model_name or "").strip()
    )

    # Ocupar a mesa
    desk.agent_id = agent_id

    # Se for Worker com supervisor, registrar como subordinado no supervisor
    if new_agent.role_type == AgentRoleType.WORKER and new_agent.supervisor_id:
        supervisor = next((a for a in workspace.agents if a.id == new_agent.supervisor_id), None)
        if supervisor:
            if agent_id not in supervisor.subordinate_ids:
                supervisor.subordinate_ids.append(agent_id)

    workspace.agents.append(new_agent)

    # Sincronizar com squads caso possua squad_id
    if new_agent.squad_id:
        squads_data = storage.load_squads()
        target_squad = next((s for s in squads_data.squads if s.id == new_agent.squad_id), None)
        if target_squad:
            if agent_id not in target_squad.member_ids:
                target_squad.member_ids.append(agent_id)
            if new_agent.tier == AgentTier.SQUAD_LEADER:
                target_squad.leader_id = agent_id
            storage.save_squads(squads_data)

    storage.save_workspace(workspace)

    # Notificar clientes conectados
    await hub.broadcast_workspace_updated(workspace.model_dump())
    await hub.broadcast_system_notice(f"✨ Novo agente contratado: {new_agent.name} ({new_agent.title}) na {desk.name}!")

    return new_agent


@app.put("/api/agents/{agent_id}", response_model=Agent)
async def update_agent(agent_id: str, req: AgentUpdateRequest):
    """Atualiza dados do agente, incluindo papel hierárquico, tier, squad, mesa e prompt."""
    workspace = storage.load_workspace()
    agent = next((a for a in workspace.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agente '{agent_id}' não encontrado."
        )

    # Se alterou de mesa
    if req.desk_id and req.desk_id != agent.desk_id:
        new_desk = next((d for d in workspace.desks if d.id == req.desk_id), None)
        if not new_desk:
            raise HTTPException(status_code=404, detail="Nova mesa não encontrada.")
        if new_desk.agent_id and new_desk.agent_id != agent.id:
            raise HTTPException(status_code=400, detail="A mesa destino já está ocupada.")
        
        # Desocupar mesa antiga
        old_desk = next((d for d in workspace.desks if d.id == agent.desk_id), None)
        if old_desk:
            old_desk.agent_id = None
        new_desk.agent_id = agent.id
        agent.desk_id = req.desk_id
        if hasattr(new_desk, "room_id") and new_desk.room_id:
            agent.room_id = new_desk.room_id

    if req.name is not None:
        agent.name = req.name.strip()
    if req.title is not None:
        agent.title = req.title.strip()
    if req.tier is not None:
        agent.tier = req.tier
    if req.avatar_id is not None:
        agent.avatar_id = req.avatar_id
    if req.system_prompt is not None:
        agent.system_prompt = req.system_prompt
    if req.model_name is not None:
        agent.model_name = req.model_name
    if req.room_id is not None:
        agent.room_id = req.room_id

    # Ajuste de squad
    old_squad_id = agent.squad_id
    if req.squad_id is not None:
        clean_squad = req.squad_id.strip() if isinstance(req.squad_id, str) else None
        agent.squad_id = clean_squad if clean_squad else None

    # Ajuste de papel hierárquico
    if req.role_type is not None:
        old_role = agent.role_type
        agent.role_type = req.role_type

        # Se deixou de ser worker, desvincular do supervisor anterior
        if old_role == AgentRoleType.WORKER and req.role_type != AgentRoleType.WORKER:
            if agent.supervisor_id:
                old_sup = next((a for a in workspace.agents if a.id == agent.supervisor_id), None)
                if old_sup and agent.id in old_sup.subordinate_ids:
                    old_sup.subordinate_ids.remove(agent.id)
                agent.supervisor_id = None

    if req.role_type == AgentRoleType.WORKER and req.supervisor_id is not None:
        # Troca de supervisor
        if agent.supervisor_id != req.supervisor_id:
            if agent.supervisor_id:
                old_sup = next((a for a in workspace.agents if a.id == agent.supervisor_id), None)
                if old_sup and agent.id in old_sup.subordinate_ids:
                    old_sup.subordinate_ids.remove(agent.id)

            agent.supervisor_id = req.supervisor_id
            new_sup = next((a for a in workspace.agents if a.id == req.supervisor_id), None)
            if new_sup and agent.id not in new_sup.subordinate_ids:
                new_sup.subordinate_ids.append(agent.id)

    # Sincronização com a base de squads
    squads_data = storage.load_squads()
    squad_modified = False

    for sq in squads_data.squads:
        # Se pertence a este squad
        if sq.id == agent.squad_id:
            if agent.id not in sq.member_ids:
                sq.member_ids.append(agent.id)
                squad_modified = True
            if agent.tier == AgentTier.SQUAD_LEADER and sq.leader_id != agent.id:
                sq.leader_id = agent.id
                squad_modified = True
            elif agent.tier != AgentTier.SQUAD_LEADER and sq.leader_id == agent.id:
                sq.leader_id = ""
                squad_modified = True
        else:
            # Não pertence a este squad: se estava vinculado, desvincular
            if agent.id in sq.member_ids and (old_squad_id == sq.id or agent.squad_id != sq.id):
                sq.member_ids = [m for m in sq.member_ids if m != agent.id]
                squad_modified = True
            if sq.leader_id == agent.id and agent.squad_id != sq.id:
                sq.leader_id = ""
                squad_modified = True

    if squad_modified:
        storage.save_squads(squads_data)

    storage.save_workspace(workspace)
    await hub.broadcast_workspace_updated(workspace.model_dump())
    return agent


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Exclui um agente, libera a mesa e limpa vínculos de subordinação."""
    workspace = storage.load_workspace()
    agent = next((a for a in workspace.agents if a.id == agent_id), None)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agente '{agent_id}' não encontrado."
        )

    # Liberar a mesa
    desk = next((d for d in workspace.desks if d.id == agent.desk_id), None)
    if desk:
        desk.agent_id = None

    # Remover de subordinados caso fosse worker
    if agent.supervisor_id:
        sup = next((a for a in workspace.agents if a.id == agent.supervisor_id), None)
        if sup and agent.id in sup.subordinate_ids:
            sup.subordinate_ids.remove(agent.id)

    # Se era supervisor, desvincular seus workers
    if agent.role_type == AgentRoleType.SUPERVISOR:
        for worker in workspace.agents:
            if worker.supervisor_id == agent.id:
                worker.supervisor_id = None

    workspace.agents = [a for a in workspace.agents if a.id != agent_id]
    storage.save_workspace(workspace)

    if desk:
        await hub.broadcast_agent_despawned(agent_id, desk.id)
    await hub.broadcast_workspace_updated(workspace.model_dump())
    await hub.broadcast_system_notice(f"Agente {agent.name} foi removido do escritório.")

    return {"deleted": True, "id": agent_id}


@app.get("/api/agents/{agent_id}/conversations")
async def get_agent_conversations(agent_id: str):
    """Retorna o histórico de conversas do agente."""
    workspace = storage.load_workspace()
    return workspace.conversations.get(agent_id, [])


@app.post("/api/chat")
async def send_chat_message(payload: ChatRequest):
    """
    Recebe um comando/mensagem do usuário para o agente e dispara a orquestração assíncrona.
    Suporta roteamento de menções AIOX (@architect, @dev, @qa, @sm, @sec, @doc, @aiox-master).
    Se o agente for do tier SUDO (ou Diretoria), executa a orquestração multinível corporativa (Agentic Agile Handoff).
    """
    workspace = storage.load_workspace()
    msg = payload.message.strip()
    target_agent_id = payload.agent_id

    # Roteamento inteligente de menções AIOX (@handle)
    if msg.startswith("@"):
        first_token = msg.split()[0].lower()
        handle_map = {
            "@aiox-master": "agent-sudo",
            "@master": "agent-sudo",
            "@pax": "agent-sudo",
            "@sudo": "agent-sudo",
            "@architect": "agent-1c137c",
            "@aria": "agent-1c137c",
            "@dev": "agent-9debfa",
            "@dex": "agent-9debfa",
            "@sm": "agent-sm",
            "@scrum": "agent-sm",
            "@morgan": "agent-sm",
            "@po": "agent-sm",
            "@pm": "agent-sm",
            "@qa": "agent-qa",
            "@quinn": "agent-qa",
            "@tester": "agent-qa",
            "@sec": "agent-ce2916",
            "@security": "agent-ce2916",
            "@cipher": "agent-ce2916",
            "@doc": "agent-doc",
            "@echo": "agent-doc",
            "@writer": "agent-doc",
        }
        if first_token in handle_map:
            mapped_id = handle_map[first_token]
            matched = next(
                (a for a in workspace.agents if a.id == mapped_id or getattr(a, "aiox_handle", None) == first_token),
                None
            )
            if matched:
                target_agent_id = matched.id

    agent = next((a for a in workspace.agents if a.id == target_agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agente não encontrado.")

    # Somente o Sudo Agent (tier SUDO ou id agent-sudo na mesa da diretoria) aciona a governança macro corporativa
    is_sudo = (
        getattr(agent, "tier", None) == AgentTier.SUDO
        or agent.id == "agent-sudo"
        or (agent.desk_id == "desk-sudo" and "sudo" in agent.name.lower())
    )
    if is_sudo:
        asyncio.create_task(multi_tier_orchestrator.handle_sudo_macro_goal(payload.message))
    else:
        # Líderes de Squad, Workers e Especialistas respondem com seu próprio motor e identidade
        asyncio.create_task(orchestrator.execute_task(target_agent_id, payload.message))

    return {"status": "started", "agent_id": target_agent_id}


@app.post("/api/sudo/chat")
async def send_sudo_macro_chat(payload: Dict[str, str]):
    """Endpoint direto para submissão de metas macro ao Sudo Agent na Diretoria."""
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="O objetivo macro não pode ser vazio.")

    asyncio.create_task(multi_tier_orchestrator.handle_sudo_macro_goal(message))
    return {"status": "started", "mode": "multi_tier_executive_governance"}


@app.get("/api/tickets", response_model=List[CrossSquadTicket])
async def list_cross_squad_tickets():
    """Retorna os tickets inter-squad ativos e resolvidos."""
    workspace = storage.load_workspace()
    return getattr(workspace, "active_tickets", []) or []


@app.post("/api/tickets/{ticket_id}/resolve")
async def resolve_ticket_api(ticket_id: str, payload: Dict[str, str]):
    """Resolve um ticket inter-squad com entrega de artefato técnico."""
    result = payload.get("result_artifact", "Entregável aprovado e verificado.")
    success = await resolve_cross_squad_ticket(ticket_id, result)
    if not success:
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' não encontrado.")
    return {"status": "resolved", "ticket_id": ticket_id}


# --- Eventos do Ciclo de Vida da Aplicação ---

@app.on_event("startup")
async def on_startup():
    """Recupera tarefas interrompidas e inicializa dados essenciais."""
    storage.ensure_initial_data()
    recovered = workflow_engine.recover_interrupted_tasks()
    if recovered:
        logger.info(f"[Startup] {recovered} tarefas interrompidas recuperadas com segurança.")


# --- Rotas de Squads e Templates de Agentes ---

@app.get("/api/agent-templates", response_model=List[AgentTemplate])
async def list_agent_templates():
    """Retorna os templates de agentes disponíveis na biblioteca."""
    squads_data = storage.load_squads()
    return squads_data.templates


@app.get("/api/squads", response_model=List[Squad])
async def list_squads():
    """Retorna a lista de squads configurados."""
    squads_data = storage.load_squads()
    return squads_data.squads


@app.post("/api/squads", response_model=Squad)
async def create_squad(req: SquadCreateRequest):
    """Cria um novo squad."""
    import time
    squads_data = storage.load_squads()
    new_squad = Squad(
        id=f"squad-{uuid.uuid4().hex[:6]}",
        name=req.name.strip(),
        description=(req.description or "").strip(),
        agent_ids=req.agent_ids,
        created_at=time.time()
    )
    squads_data.squads.append(new_squad)
    storage.save_squads(squads_data)
    return new_squad


@app.get("/api/squads/{squad_id}", response_model=Squad)
async def get_squad(squad_id: str):
    squads_data = storage.load_squads()
    squad = next((s for s in squads_data.squads if s.id == squad_id), None)
    if not squad:
        raise HTTPException(status_code=404, detail="Squad não encontrado.")
    return squad


@app.put("/api/squads/{squad_id}", response_model=Squad)
async def update_squad(squad_id: str, req: SquadUpdateRequest):
    squads_data = storage.load_squads()
    squad = next((s for s in squads_data.squads if s.id == squad_id), None)
    if not squad:
        raise HTTPException(status_code=404, detail="Squad não encontrado.")
    if req.name is not None:
        squad.name = req.name.strip()
    if req.description is not None:
        squad.description = req.description.strip()
    if req.agent_ids is not None:
        squad.agent_ids = req.agent_ids
    storage.save_squads(squads_data)
    return squad


@app.delete("/api/squads/{squad_id}")
async def delete_squad(squad_id: str):
    squads_data = storage.load_squads()
    squad = next((s for s in squads_data.squads if s.id == squad_id), None)
    if not squad:
        raise HTTPException(status_code=404, detail="Squad não encontrado.")
    squads_data.squads = [s for s in squads_data.squads if s.id != squad_id]
    storage.save_squads(squads_data)
    return {"deleted": True, "id": squad_id}


@app.get("/api/squads/{squad_id}/export", response_model=SquadExport)
async def export_squad(squad_id: str):
    try:
        return storage.export_squad(squad_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/squads/import", response_model=Squad)
async def import_squad(export_data: SquadExport):
    try:
        return storage.import_squad(export_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao importar squad: {e}")


# --- Rotas de Workflows ---

@app.get("/api/workflows", response_model=List[WorkflowTemplate])
async def list_workflows():
    return storage.load_workflows().workflows


@app.post("/api/workflows", response_model=WorkflowTemplate)
async def create_workflow(req: WorkflowCreateRequest):
    workflows_data = storage.load_workflows()
    new_wf = WorkflowTemplate(
        id=f"wf-{uuid.uuid4().hex[:6]}",
        name=req.name.strip(),
        description=(req.description or "").strip(),
        steps=req.steps
    )
    workflows_data.workflows.append(new_wf)
    storage.save_workflows(workflows_data)
    return new_wf


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowTemplate)
async def get_workflow(workflow_id: str):
    workflows_data = storage.load_workflows()
    wf = next((w for w in workflows_data.workflows if w.id == workflow_id), None)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow não encontrado.")
    return wf


@app.put("/api/workflows/{workflow_id}", response_model=WorkflowTemplate)
async def update_workflow(workflow_id: str, req: WorkflowUpdateRequest):
    workflows_data = storage.load_workflows()
    wf = next((w for w in workflows_data.workflows if w.id == workflow_id), None)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow não encontrado.")
    if req.name is not None:
        wf.name = req.name.strip()
    if req.description is not None:
        wf.description = req.description.strip()
    if req.steps is not None:
        wf.steps = req.steps
    storage.save_workflows(workflows_data)
    return wf


@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    workflows_data = storage.load_workflows()
    wf = next((w for w in workflows_data.workflows if w.id == workflow_id), None)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow não encontrado.")
    workflows_data.workflows = [w for w in workflows_data.workflows if w.id != workflow_id]
    storage.save_workflows(workflows_data)
    return {"deleted": True, "id": workflow_id}


# --- Rotas de Tarefas e Execução da Máquina de Estados ---

@app.get("/api/tasks", response_model=List[TaskPacket])
async def list_tasks(state: Optional[TaskState] = None):
    tasks_data = storage.load_tasks()
    if state:
        return [t for t in tasks_data.tasks if t.state == state]
    return tasks_data.tasks


@app.post("/api/tasks", response_model=TaskPacket)
async def create_task(req: TaskCreateRequest):
    import time
    from backend.models import TaskEvent
    workflows_data = storage.load_workflows()
    wf = next((w for w in workflows_data.workflows if w.id == req.workflow_id), None)
    if not wf:
        raise HTTPException(status_code=400, detail=f"Workflow '{req.workflow_id}' não encontrado.")

    tasks_data = storage.load_tasks()
    now = time.time()
    new_task = TaskPacket(
        id=f"task-{uuid.uuid4().hex[:6]}",
        title=req.title.strip(),
        objective=req.objective.strip(),
        workflow_id=req.workflow_id,
        squad_id=req.squad_id,
        state=TaskState.QUEUED,
        created_at=now,
        updated_at=now
    )
    new_task.events.append(TaskEvent(
        id=f"evt-{uuid.uuid4().hex[:8]}",
        task_id=new_task.id,
        event_type="task.created",
        message=f"Tarefa '{new_task.title}' criada e enfileirada no workflow '{wf.name}'.",
        timestamp=now,
        payload={"workflow_id": wf.id}
    ))

    tasks_data.tasks.append(new_task)
    storage.save_tasks(tasks_data)

    await hub.broadcast({
        "event": "task.created",
        "task_id": new_task.id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": new_task.model_dump()
    })
    return new_task


@app.get("/api/tasks/{task_id}", response_model=TaskPacket)
async def get_task(task_id: str):
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    return task


@app.put("/api/tasks/{task_id}", response_model=TaskPacket)
async def update_task(task_id: str, req: TaskUpdateRequest):
    import time
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if req.title is not None:
        task.title = req.title.strip()
    if req.objective is not None:
        task.objective = req.objective.strip()
    task.updated_at = time.time()
    storage.save_tasks(tasks_data)
    return task


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if workflow_engine.is_task_running(task_id):
        raise HTTPException(status_code=400, detail="Não é possível excluir uma tarefa em execução ativa.")
    tasks_data.tasks = [t for t in tasks_data.tasks if t.id != task_id]
    storage.save_tasks(tasks_data)
    return {"deleted": True, "id": task_id}


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str):
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")

    if workflow_engine.is_task_running(task_id):
        raise HTTPException(status_code=400, detail="Esta tarefa já está em execução.")

    if task.state not in (TaskState.QUEUED, TaskState.WAITING_APPROVAL, TaskState.QUALITY_GATE):
        raise HTTPException(status_code=400, detail=f"Tarefa no estado {task.state.value} não pode ser iniciada.")

    # Dispara a execução assíncrona da máquina de estados
    asyncio.create_task(workflow_engine.execute_task(task_id))
    return {"status": "started", "task_id": task_id}


@app.post("/api/tasks/{task_id}/cancel", response_model=TaskPacket)
async def cancel_task(task_id: str):
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    try:
        workflow_engine.transition_state(task, TaskState.CANCELLED, reason="Cancelamento solicitado pelo usuário.")
        storage.save_tasks(tasks_data)
        await hub.broadcast({"type": "task.updated", "task": task.model_dump()})
        return task
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/tasks/{task_id}/retry", response_model=TaskPacket)
async def retry_task(task_id: str):
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if task.state != TaskState.FAILED:
        raise HTTPException(status_code=400, detail=f"Apenas tarefas no estado FAILED podem ser reiniciadas (atual: {task.state.value}).")
    try:
        workflow_engine.transition_state(task, TaskState.QUEUED, reason="Reinício solicitado pelo usuário após falha.")
        storage.save_tasks(tasks_data)
        await hub.broadcast({"type": "task.updated", "task": task.model_dump()})
        return task
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Rotas de Aprovação Humana e Quality Gates ---

@app.get("/api/approvals/pending", response_model=List[ApprovalRequest])
async def list_pending_approvals():
    """Retorna todas as aprovações pendentes em todas as tarefas."""
    tasks_data = storage.load_tasks()
    pending: List[ApprovalRequest] = []
    for task in tasks_data.tasks:
        for apprv in task.approvals:
            if apprv.status == "pending":
                pending.append(apprv)
    return pending


@app.get("/api/tasks/{task_id}/approvals", response_model=List[ApprovalRequest])
async def list_task_approvals(task_id: str):
    """Retorna o histórico de aprovações e propostas de uma tarefa específica."""
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    return task.approvals


@app.post("/api/tasks/{task_id}/approvals/{approval_id}/approve", response_model=TaskPacket)
async def approve_task_proposal(
    task_id: str,
    approval_id: str,
    body: Optional[ApprovalDecisionRequest] = None
):
    """
    Aprova uma alteração proposta ou avanço de etapa, aplicando arquivos ao workspace de forma segura
    e retomando a execução do workflow.
    """
    notes = body.notes if body else ""
    try:
        updated_task = await workflow_engine.apply_approval_decision(
            task_id=task_id,
            approval_id=approval_id,
            approved=True,
            notes=notes
        )
        return updated_task
    except ApprovalNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ApprovalAlreadyDecidedError, InvalidTransitionError, SecurityPathError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erro ao processar aprovação: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao processar aprovação: {str(e)}")


@app.post("/api/tasks/{task_id}/approvals/{approval_id}/reject", response_model=TaskPacket)
async def reject_task_proposal(
    task_id: str,
    approval_id: str,
    body: Optional[ApprovalDecisionRequest] = None
):
    """
    Rejeita uma proposta de alteração. Permite registrar justificativa e opcionalmente
    devolver para refação (action="retry") se o limite de revisões não tiver sido atingido.
    """
    notes = body.notes if body else ""
    action = body.action if body else None
    try:
        updated_task = await workflow_engine.apply_approval_decision(
            task_id=task_id,
            approval_id=approval_id,
            approved=False,
            notes=notes,
            action=action
        )
        return updated_task
    except ApprovalNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ApprovalAlreadyDecidedError, InvalidTransitionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erro ao processar rejeição: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao processar rejeição: {str(e)}")


# --- Diagnósticos do Sistema (Etapa 5) ---

@app.get("/api/system/diagnostics", response_model=DiagnosticResult)
async def get_system_diagnostics():
    """Retorna diagnóstico completo do sistema (LLM, workspace, persistência, ambiente)."""
    return await run_system_diagnostics()


@app.post("/api/system/diagnostics/run", response_model=DiagnosticResult)
async def trigger_system_diagnostics():
    """Executa novo diagnóstico, transmite evento via WebSocket e retorna resultado."""
    diag = await run_system_diagnostics()
    await hub.broadcast({
        "event": "system.diagnostic_result",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": diag.model_dump()
    })
    return diag


# --- Relatório da Tarefa (Etapa 5) ---

@app.get("/api/tasks/{task_id}/report")
async def get_task_report(task_id: str):
    """
    Recupera o relatório Markdown gerado para uma tarefa concluída.
    Se o relatório ainda não tiver sido gerado em disco, gera dinamicamente.
    """
    tasks_data = storage.load_tasks()
    task = next((t for t in tasks_data.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail=f"Tarefa '{task_id}' não encontrada.")

    report_artifact = next(
        (a for a in task.artifacts if a.content_type == "text/markdown" or "relatorio" in a.file_path.lower()),
        None
    )

    clean_name = f"relatorio_tarefa_{task.id}.md"
    config = storage.load_config()
    workspace_dir = Path(config.workspace_dir or str(BASE_DIR)).resolve()
    report_path = workspace_dir / clean_name

    if report_path.exists():
        content = report_path.read_text(encoding="utf-8")
    elif report_artifact and report_artifact.content:
        content = report_artifact.content
    else:
        clean_name, content = workflow_engine.generate_final_report(task)
        storage.save_tasks(tasks_data, backup=False)

    return {
        "task_id": task.id,
        "task_title": task.title,
        "status": task.state.value,
        "report_filename": clean_name,
        "content": content
    }


# ===================================================================
# --- AIOX Memory Layer & ADE Endpoints (Epic 7 Architecture) ---
# ===================================================================

@app.get("/api/memory/summary")
async def get_memory_summary():
    """Retorna o resumo contextual da memória persistente AIOX."""
    return {"prompt_context": memory_layer.get_memory_context_prompt()}


@app.get("/api/memory/decisions")
async def get_memory_decisions():
    """Retorna todas as decisões arquiteturais (ADRs) registradas."""
    return memory_layer.list_decisions()


@app.get("/api/memory/gotchas")
async def get_memory_gotchas():
    """Retorna as armadilhas e edge cases conhecidos."""
    return memory_layer.list_gotchas()


@app.get("/api/memory/insights")
async def get_memory_insights():
    """Retorna os insights aprendidos entre sessões."""
    return memory_layer.list_insights()


@app.get("/api/memory/patterns")
async def get_memory_patterns():
    """Retorna os padrões de código e arquitetura registrados."""
    return memory_layer.list_patterns()


@app.post("/api/memory")
async def record_memory_item(payload: Dict[str, Any]):
    """Registra uma nova entrada na memória persistente AIOX."""
    cat = payload.get("category", "insight").lower()
    title = payload.get("title", "Nota Registrada")
    content = payload.get("content", "")
    author = payload.get("author", "User")
    tags = payload.get("tags", [])

    if not content:
        raise HTTPException(status_code=400, detail="O campo 'content' é obrigatório.")

    if cat in ("decision", "adr"):
        entry = memory_layer.record_decision(title, content, author, tags)
    elif cat in ("gotcha", "armadilha"):
        entry = memory_layer.record_gotcha(title, content, author, tags)
    elif cat in ("pattern", "padrao"):
        entry = memory_layer.record_pattern(title, content, author, tags)
    else:
        entry = memory_layer.record_insight(title, content, author, tags)

    await hub.broadcast_system_notice(
        f"🧠 [AIOX:MEMORY] Nova entrada '{entry['id']}' ({cat}) gravada na memória persistente!"
    )
    return entry


@app.post("/api/memory/critique")
async def trigger_ade_self_critique(payload: Optional[Dict[str, Any]] = None):
    """Executa a auto-crítica ADE (Autonomous Development Engine) sobre o código no sandbox."""
    target_dir = payload.get("target_dir", "src") if payload else "src"
    critique = memory_layer.perform_ade_self_critique(target_dir)
    await hub.broadcast_system_notice(
        f"🔍 [AIOX:ADE] Auto-crítica concluída: Score {critique['score']}/100 — {critique['verdict']}"
    )
    return critique


# ===================================================================
# --- AIOX Squad Manifest (YAML Import/Export) ---
# ===================================================================

@app.get("/api/squads/{squad_id}/export-yaml")
async def export_squad_yaml(squad_id: str):
    """Exporta manifesto do squad no formato padrão squad.yaml do ecossistema AIOX."""
    squads_data = storage.load_squads()
    squad = next((s for s in squads_data.squads if s.id == squad_id), None)
    if not squad:
        raise HTTPException(status_code=404, detail=f"Squad '{squad_id}' não encontrado.")

    manifest = {
        "version": "1.0",
        "kind": "aiox-squad",
        "metadata": {
            "name": squad.name,
            "id": squad.id,
            "room_id": squad.room_id,
            "color_theme": squad.color_theme,
            "tags": squad.domain_tags,
            "description": squad.description
        },
        "spec": {
            "leader": squad.leader_id,
            "members": squad.member_ids,
            "quality_gates": ["ast_syntax", "security_audit", "ade_critique", "story_dod"]
        }
    }
    yaml_text = yaml.dump(manifest, sort_keys=False, allow_unicode=True)
    return {"squad_id": squad_id, "yaml_manifest": yaml_text}


@app.post("/api/squads/import-yaml")
async def import_squad_yaml(payload: Dict[str, Any]):
    """Importa e registra um Squad a partir de um manifesto AIOX squad.yaml."""
    yaml_text = payload.get("yaml_text", "")
    if not yaml_text:
        raise HTTPException(status_code=400, detail="Campo 'yaml_text' é obrigatório.")

    try:
        data = yaml.safe_load(yaml_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML inválido: {str(e)}")

    metadata = data.get("metadata", {})
    spec = data.get("spec", {})

    squad_id = metadata.get("id") or f"squad-{uuid.uuid4().hex[:6]}"
    squad_name = metadata.get("name", "Imported Squad")
    room_id = metadata.get("room_id", "room_dev")
    color_theme = metadata.get("color_theme", "#38bdf8")
    tags = metadata.get("tags", [])
    desc = metadata.get("description", "")
    leader_id = spec.get("leader", "")
    members = spec.get("members", [])

    squads_data = storage.load_squads()
    existing = next((s for s in squads_data.squads if s.id == squad_id), None)
    if existing:
        existing.name = squad_name
        existing.room_id = room_id
        existing.color_theme = color_theme
        existing.domain_tags = tags
        existing.description = desc
        existing.leader_id = leader_id
        existing.member_ids = members
        saved_squad = existing
    else:
        new_squad = Squad(
            id=squad_id,
            name=squad_name,
            room_id=room_id,
            color_theme=color_theme,
            domain_tags=tags,
            description=desc,
            leader_id=leader_id,
            member_ids=members
        )
        squads_data.squads.append(new_squad)
        saved_squad = new_squad

    storage.save_squads(squads_data, backup=False)
    await hub.broadcast_system_notice(f"📦 [AIOX:SQUAD] Squad '{squad_name}' importado com sucesso via squad.yaml!")
    return {"status": "imported", "squad": saved_squad.model_dump()}




