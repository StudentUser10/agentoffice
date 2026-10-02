"""
AgentOffice 2D - Pydantic Data Models and Schemas
Suporte completo para configuração, agentes, hierarquia, squads, templates,
workflows, quality gates, aprovação humana e pacotes de tarefas.
"""

from enum import Enum
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# --- Enums de Agentes e Tarefas ---

class AgentRoleType(str, Enum):
    SOLO = "solo"
    SUPERVISOR = "supervisor"
    WORKER = "worker"


class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    WALKING = "walking"
    REPORTING = "reporting"


class TaskState(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    QUALITY_GATE = "QUALITY_GATE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Transições válidas de estados de tarefas
VALID_TASK_TRANSITIONS: Dict[TaskState, List[TaskState]] = {
    TaskState.QUEUED: [TaskState.IN_PROGRESS, TaskState.CANCELLED],
    TaskState.IN_PROGRESS: [
        TaskState.QUALITY_GATE,
        TaskState.WAITING_APPROVAL,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    ],
    TaskState.QUALITY_GATE: [
        TaskState.IN_PROGRESS,
        TaskState.WAITING_APPROVAL,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    ],
    TaskState.WAITING_APPROVAL: [
        TaskState.IN_PROGRESS,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    ],
    TaskState.COMPLETED: [],
    TaskState.FAILED: [TaskState.QUEUED],  # Permite retry/reinício
    TaskState.CANCELLED: [TaskState.QUEUED],
}


class WorkflowActionType(str, Enum):
    GENERATE = "generate"
    REVIEW = "review"
    PREPARE_CHANGE = "prepare_change"


# --- Configuração do Sistema ---

class UIPreferences(BaseModel):
    theme: str = "retro-dark"
    sound_enabled: bool = True
    pixel_scale: int = 2


class AppConfig(BaseModel):
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "llama3:latest"
    api_keys: Dict[str, str] = Field(default_factory=dict)
    workspace_dir: str = ""
    ui_preferences: UIPreferences = Field(default_factory=UIPreferences)
    configured: bool = False


class ProviderInfo(BaseModel):
    id: str
    name: str
    default_url: str
    requires_key: bool


class ConfigResponse(BaseModel):
    """Resposta pública segura sem chaves de API"""
    provider: str
    base_url: str
    model: str
    has_api_keys: Dict[str, bool]
    workspace_dir: str
    ui_preferences: UIPreferences
    configured: bool
    supported_providers: List[ProviderInfo] = Field(default_factory=list)


class ConfigUpdateRequest(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    provider_keys: Optional[Dict[str, str]] = None
    clear_keys: Optional[List[str]] = None
    workspace_dir: Optional[str] = None
    ui_preferences: Optional[UIPreferences] = None
    configured: Optional[bool] = None

    @field_validator("base_url")
    @classmethod
    def sanitize_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.strip().rstrip("/")
        return v


class TestConnectionRequest(BaseModel):
    provider: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    models: List[str] = Field(default_factory=list)
    details: Optional[str] = None


class DetectModelsResponse(BaseModel):
    available: bool
    models: List[str] = Field(default_factory=list)
    message: str


class DirectorySelectResponse(BaseModel):
    selected: bool
    path: Optional[str] = None
    message: str


# --- Estrutura do Escritório e Agentes ---

class Desk(BaseModel):
    id: str
    name: str
    x: int
    y: int
    seat_x: int
    seat_y: int
    front_x: int
    front_y: int
    width: int = 76
    height: int = 48
    agent_id: Optional[str] = None


class SpawnSubagentParams(BaseModel):
    name: str = Field(..., description="Nome do subagente (ex: 'SQL_Architect', 'CSS_Polisher').")
    role_title: str = Field(..., description="Cargo e especialidade formal do agente.")
    avatar_id: str = Field(default="avatar_1", description="ID visual do sprite.")
    
    # O QUÊ: Escopo e Limites Concretos
    what_exact_task: str = Field(
        ..., 
        description="Descrição detalhada do entregável exato. Proibido ser vago. Deve listar arquivos específicos a criar/editar."
    )
    what_out_of_scope: str = Field(
        ..., 
        description="O que o subagente NÃO tem permissão de fazer (limites de escopo)."
    )
    
    # QUANDO: Gatilhos e Condições de Execução
    when_triggers: str = Field(
        ..., 
        description="Quando o subagente inicia, quais pré-requisitos/arquivos devem existir antes e dependências."
    )
    
    # COMO: Metodologia, Formato e Regras
    how_instructions: str = Field(
        ..., 
        description="Passo a passo rigoroso de execução, convenções de código, restrições e formato exato da resposta."
    )
    
    # Ferramentas e Recursos Permitidos
    allowed_tools: List[str] = Field(
        default=["fs_read_file", "fs_write_file", "fs_create_directory", "fs_list_directory"],
        description="Lista explícita de ferramentas que o subagente pode usar."
    )
    
    # Condição de Encerramento (Exit Condition)
    exit_condition: str = Field(
        ..., 
        description="Critério objetivo para considerar o trabalho concluído e liberar a mesa (ex: 'Arquivo schema.sql gerado e validado')."
    )
    
    model_override: Optional[str] = Field(
        default=None, 
        description="Modelo específico para este subagente (ex: modelo rápido ou local)."
    )


class Agent(BaseModel):
    id: str
    name: str
    title: str                     # Ex: "Tech Lead", "Backend Dev"
    avatar_id: str = "avatar_1"
    role_type: AgentRoleType = AgentRoleType.SOLO
    supervisor_id: Optional[str] = None     # Se for WORKER, aponta para o SUPERVISOR
    subordinate_ids: List[str] = Field(default_factory=list) # Se for SUPERVISOR
    desk_id: str
    system_prompt: str = "Você é um assistente de IA focado e prestativo."
    model_name: str = ""
    state: AgentState = AgentState.IDLE
    mission: Optional[SpawnSubagentParams] = None
    is_temporary: bool = False


class AgentCreateRequest(BaseModel):
    name: str
    title: str
    avatar_id: str = "avatar_1"
    role_type: AgentRoleType = AgentRoleType.SOLO
    supervisor_id: Optional[str] = None
    desk_id: str
    system_prompt: Optional[str] = None
    model_name: Optional[str] = None


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    avatar_id: Optional[str] = None
    role_type: Optional[AgentRoleType] = None
    supervisor_id: Optional[str] = None
    desk_id: Optional[str] = None
    system_prompt: Optional[str] = None
    model_name: Optional[str] = None


class ChatMessage(BaseModel):
    sender: str
    text: str
    timestamp: float
    role: str = "user"             # "user", "assistant", "system"


class ChatRequest(BaseModel):
    agent_id: str
    message: str


class WorkspaceData(BaseModel):
    version: str = "2.0"
    agents: List[Agent] = Field(default_factory=list)
    desks: List[Desk] = Field(default_factory=list)
    conversations: Dict[str, List[dict]] = Field(default_factory=dict)


# --- Squads e Templates de Agentes ---

class AgentTemplate(BaseModel):
    id: str
    name: str
    title: str
    role_type: AgentRoleType = AgentRoleType.WORKER
    system_prompt: str
    avatar_id: str = "avatar_1"
    default_model: str = ""


class Squad(BaseModel):
    id: str
    name: str
    description: str = ""
    agent_ids: List[str] = Field(default_factory=list)
    created_at: float


class SquadExport(BaseModel):
    """Pacote seguro de exportação e importação de squad (sem segredos ou chaves)"""
    version: str = "1.0"
    squad: Squad
    agent_templates: List[AgentTemplate] = Field(default_factory=list)


class SquadsData(BaseModel):
    templates: List[AgentTemplate] = Field(default_factory=list)
    squads: List[Squad] = Field(default_factory=list)


# --- Workflows e Quality Gates ---

class QualityGateRule(BaseModel):
    id: str
    name: str
    description: str = ""
    min_score: Optional[float] = None
    required_criteria: List[str] = Field(default_factory=list)
    max_retries: int = 2
    auto_reject_keywords: List[str] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    id: str
    name: str
    required_role: str   # ex: "supervisor", "tech_lead", "developer", "qa", "researcher", "writer"
    action_type: WorkflowActionType = WorkflowActionType.GENERATE
    instructions: str
    review_criteria: Optional[List[str]] = None
    requires_human_approval: bool = False
    max_revisions: int = 2


class WorkflowTemplate(BaseModel):
    id: str
    name: str
    description: str = ""
    steps: List[WorkflowStep] = Field(default_factory=list)


class WorkflowsData(BaseModel):
    workflows: List[WorkflowTemplate] = Field(default_factory=list)


# --- Pacotes de Tarefas, Artefatos, Aprovação e Diagnósticos ---

class TaskArtifact(BaseModel):
    id: str
    name: str
    file_path: str
    content_type: str = "text/markdown"
    diff: Optional[str] = None
    content: Optional[str] = None
    created_at: float


class ApprovalRequest(BaseModel):
    id: str
    task_id: str
    step_id: str
    summary: str
    proposed_diff: Optional[str] = None
    proposed_content: Optional[str] = None
    affected_file: Optional[str] = None
    status: str = "pending"  # "pending", "approved", "rejected"
    feedback: Optional[str] = None
    created_at: float
    decided_at: Optional[float] = None


class TaskEvent(BaseModel):
    id: str
    task_id: str
    event_type: str
    message: str
    timestamp: float
    payload: Dict[str, Any] = Field(default_factory=dict)


class DiagnosticResult(BaseModel):
    component: str
    status: str  # "success", "warning", "failure"
    description: str
    timestamp: float
    details: Optional[str] = None


class TaskPacket(BaseModel):
    id: str
    title: str
    objective: str
    workflow_id: str
    squad_id: Optional[str] = None
    current_step_index: int = 0
    assigned_agent_id: Optional[str] = None
    state: TaskState = TaskState.QUEUED
    artifacts: List[TaskArtifact] = Field(default_factory=list)
    summary: str = ""
    decisions: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    pending_items: List[str] = Field(default_factory=list)
    events: List[TaskEvent] = Field(default_factory=list)
    revision_count: int = 0
    approvals: List[ApprovalRequest] = Field(default_factory=list)
    created_at: float
    updated_at: float


class TasksData(BaseModel):
    tasks: List[TaskPacket] = Field(default_factory=list)


# --- Schemas de Requisição para CRUD de Squads, Workflows e Tarefas ---

class SquadCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    agent_ids: List[str] = Field(default_factory=list)


class SquadUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_ids: Optional[List[str]] = None


class WorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    steps: List[WorkflowStep]


class WorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[List[WorkflowStep]] = None


class TaskCreateRequest(BaseModel):
    title: str
    objective: str
    workflow_id: str
    squad_id: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    objective: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    notes: Optional[str] = ""
    action: Optional[str] = None  # "retry" ou "fail" (para rejeição)


# --- Diagnósticos do Sistema ---

class DiagnosticItem(BaseModel):
    name: str                           # ex: "Ollama (Local)", "Workspace I/O", "Persistência"
    status: str                         # "healthy", "warning", "error"
    message: str                        # Mensagem amigável com resultado
    latency_ms: Optional[float] = None  # Latência em milissegundos se aplicável
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)


class DiagnosticResult(BaseModel):
    overall_status: str                 # "healthy", "warning", "error"
    timestamp: float = Field(default_factory=time.time)
    items: List[DiagnosticItem] = Field(default_factory=list)
    system_info: Dict[str, Any] = Field(default_factory=dict)

