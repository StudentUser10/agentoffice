"""
AgentOffice 2D - Workflow Engine & State Machine
Motor assíncrono para execução de workflows, transições de estado estritas,
seleção de agentes, isolamento de falhas, quality gates e aprovação humana.
"""

import asyncio
import difflib
import logging
import os
from pathlib import Path
import time
import uuid
from typing import Dict, List, Optional, Set, Tuple

from backend.config import BASE_DIR, is_safe_workspace_child_path
from backend.llm_client import LLMClient, LLMClientError
from backend.models import (
    Agent,
    AgentRoleType,
    AgentState,
    ApprovalRequest,
    QualityGateRule,
    Squad,
    TaskArtifact,
    TaskEvent,
    TaskPacket,
    TasksData,
    TaskState,
    VALID_TASK_TRANSITIONS,
    WorkflowActionType,
    WorkflowStep,
    WorkflowTemplate,
    WorkspaceData,
)
from backend.storage import storage
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.workflow_engine")


class WorkflowEngineError(Exception):
    """Exceção base do motor de workflows."""
    pass


class InvalidTransitionError(WorkflowEngineError):
    """Exceção levantada quando uma transição de estado não permitida é solicitada."""
    pass


class TaskAlreadyRunningError(WorkflowEngineError):
    """Exceção levantada ao tentar executar simultaneamente uma tarefa já ativa."""
    pass


class ApprovalNotFoundError(WorkflowEngineError):
    """Exceção levantada quando uma aprovação solicitada não existe na tarefa."""
    pass


class ApprovalAlreadyDecidedError(WorkflowEngineError):
    """Exceção levantada ao tentar decidir uma aprovação que não está pendente."""
    pass


class SecurityPathError(WorkflowEngineError):
    """Exceção levantada quando uma operação de arquivo tenta escapar do workspace."""
    pass


class WorkflowEngine:
    def __init__(self):
        self._running_tasks: Set[str] = set()

    def is_task_running(self, task_id: str) -> bool:
        return task_id in self._running_tasks

    def transition_state(
        self,
        task: TaskPacket,
        new_state: TaskState,
        reason: str = "",
        payload: Optional[Dict] = None
    ) -> None:
        """
        Valida e executa a transição de estado do pacote de tarefas.
        Rejeita transições ilegais conforme VALID_TASK_TRANSITIONS.
        Registra evento de histórico.
        """
        if task.state == new_state:
            task.updated_at = time.time()
            if reason:
                event = TaskEvent(
                    id=f"evt-{uuid.uuid4().hex[:8]}",
                    task_id=task.id,
                    event_type="task.updated",
                    message=reason,
                    timestamp=task.updated_at,
                    payload={"state": task.state.value, **(payload or {})}
                )
                task.events.append(event)
            return

        if new_state not in VALID_TASK_TRANSITIONS.get(task.state, []):
            raise InvalidTransitionError(
                f"Transição inválida: Não é permitido mudar de {task.state.value} para {new_state.value}."
            )

        old_state = task.state
        task.state = new_state
        task.updated_at = time.time()

        # Registrar evento no histórico da tarefa
        event = TaskEvent(
            id=f"evt-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            event_type="task.updated",
            message=f"Estado alterado de {old_state.value} para {new_state.value}. {reason}".strip(),
            timestamp=task.updated_at,
            payload={
                "old_state": old_state.value,
                "new_state": new_state.value,
                **(payload or {})
            }
        )
        task.events.append(event)

    def find_matching_agent(
        self,
        required_role: str,
        workspace: WorkspaceData,
        squad: Optional[Squad] = None
    ) -> Optional[Agent]:
        """
        Localiza um agente compatível no workspace, priorizando membros do squad.
        """
        agents = workspace.agents
        if not agents:
            return None

        # Priorizar agentes que pertencem ao squad especificado
        squad_agent_ids = set(squad.agent_ids) if squad else set()
        candidates = sorted(
            agents,
            key=lambda a: 0 if a.id in squad_agent_ids else 1
        )

        role_lower = required_role.lower()

        # 1. Correspondência com Supervisor / Tech Lead / Arquiteto
        if role_lower in ("supervisor", "tech_lead", "lead", "arquiteto"):
            for a in candidates:
                if a.role_type == AgentRoleType.SUPERVISOR or "lead" in a.title.lower() or "arquiteto" in a.title.lower():
                    return a

        # 2. Correspondência com QA / Revisor / Auditor
        if role_lower in ("qa", "revisor", "reviewer", "auditor"):
            for a in candidates:
                if "qa" in a.title.lower() or "revisor" in a.title.lower() or "auditor" in a.title.lower():
                    return a

        # 3. Correspondência com Desenvolvedor / Worker / Engenheiro
        if role_lower in ("worker", "developer", "dev", "engenheiro", "python"):
            for a in candidates:
                if a.role_type == AgentRoleType.WORKER and ("dev" in a.title.lower() or "eng" in a.title.lower() or "python" in a.title.lower()):
                    return a

        # 4. Fallback: qualquer agente que cumpra role_type se especificado, ou o primeiro
        for a in candidates:
            if role_lower == a.role_type.value:
                return a

        return candidates[0]

    def parse_change_proposal(
        self,
        step_output: str,
        default_filename: str = "proposta_alteracao.md"
    ) -> Tuple[str, str, str]:
        """
        Extrai (affected_file, summary, proposed_content) a partir da saída gerada.
        Suporta o padrão estruturado (ARQUIVO_ALVO:, RESUMO:, CONTEUDO_PROPOSTO:) com fallback seguro.
        """
        lines = step_output.strip().splitlines()
        affected_file = default_filename
        summary = ""
        content_lines = []
        in_content = False

        for line in lines:
            stripped = line.strip()
            if stripped.upper().startswith("ARQUIVO_ALVO:") or stripped.upper().startswith("ARQUIVO:"):
                raw_path = stripped.split(":", 1)[1].strip().strip("\"' `")
                if raw_path:
                    affected_file = raw_path
            elif stripped.upper().startswith("RESUMO:"):
                summary = stripped.split(":", 1)[1].strip()
            elif stripped.upper().startswith("CONTEUDO_PROPOSTO:") or stripped.upper().startswith("CONTEUDO:"):
                in_content = True
            elif in_content:
                content_lines.append(line)
            elif not summary and stripped and not stripped.startswith("#"):
                summary = stripped[:140]

        if in_content and content_lines:
            proposed_content = "\n".join(content_lines).strip()
        else:
            proposed_content = step_output.strip()

        if not summary:
            summary = f"Proposta de alteração para {affected_file}"

        return affected_file, summary, proposed_content

    def generate_unified_diff(
        self,
        affected_file: str,
        proposed_content: str,
        workspace_dir: str
    ) -> str:
        """
        Gera um diff unificado legível entre o arquivo existente na pasta de trabalho
        (caso exista) e a proposta de alteração. Não aplica nenhuma alteração ao disco.
        """
        original_lines = []
        if workspace_dir and is_safe_workspace_child_path(affected_file, workspace_dir):
            resolved_path = (Path(workspace_dir).resolve() / affected_file).resolve()
            if resolved_path.exists() and resolved_path.is_file():
                try:
                    with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                        original_lines = f.read().splitlines(keepends=True)
                except Exception as e:
                    logger.warning(f"Não foi possível ler arquivo existente para diff: {e}")
                    original_lines = []

        proposed_lines = [line + "\n" for line in proposed_content.splitlines()]
        diff_gen = difflib.unified_diff(
            original_lines,
            proposed_lines,
            fromfile=f"a/{affected_file}",
            tofile=f"b/{affected_file}"
        )
        diff_str = "".join(diff_gen)
        if not diff_str.strip():
            diff_str = (
                f"--- /dev/null\n+++ b/{affected_file}\n@@ Novo arquivo @@\n"
                + "".join(f"+{line}" for line in proposed_lines[:40])
            )
        return diff_str

    def evaluate_quality_gate(
        self,
        step_output: str,
        review_criteria: Optional[List[str]] = None,
        auto_reject_keywords: Optional[List[str]] = None
    ) -> Tuple[bool, str, List[str]]:
        """
        Avalia o resultado de uma etapa de revisão contra critérios e palavras-chave.
        Retorna (is_approved, feedback, evaluated_criteria).
        """
        criteria = review_criteria or ["Qualidade da solução", "Atendimento aos requisitos"]
        output_upper = step_output.upper()
        output_lower = step_output.lower()

        # 1. Validação automatizada: rejeição imediata se palavra-chave proibida for encontrada
        if auto_reject_keywords:
            for kw in auto_reject_keywords:
                if kw.lower() in output_lower:
                    return False, f"Rejeição automatizada: palavra-chave rejeitada '{kw}' detectada.", criteria

        # 2. Avaliação de decisão explícita
        if any(tag in output_upper for tag in ["DECISÃO: REPROVADO", "DECISAO: REPROVADO", "[REPROVADO]", "STATUS: REPROVADO", "DECISÃO: REJEITADO"]):
            is_approved = False
        elif any(tag in output_upper for tag in ["DECISÃO: APROVADO", "DECISAO: APROVADO", "[APROVADO]", "STATUS: APROVADO"]):
            is_approved = True
        else:
            # Heurística quando o revisor não utilizou a tag exata
            negative_indicators = ["reprovad", "rejeitad", "não atende", "nao atende", "falhou", "insuficiente", "defeito crítico"]
            if any(ind in output_lower for ind in negative_indicators):
                is_approved = False
            else:
                is_approved = True

        # 3. Extração do feedback
        if "FEEDBACK:" in output_upper:
            parts = step_output.split("FEEDBACK:", 1)
            feedback = parts[1].strip()
        else:
            feedback = step_output.strip()

        return is_approved, feedback, criteria

    async def execute_task(self, task_id: str) -> None:
        """
        Executa uma tarefa assincronamente através de suas etapas de workflow.
        Garante concorrência segura, controle de timeouts (45s), isolamento de falhas,
        quality gates com limite de refações e suspensão segura para aprovação humana.
        """
        if task_id in self._running_tasks:
            raise TaskAlreadyRunningError(f"A tarefa '{task_id}' já está em execução.")

        self._running_tasks.add(task_id)
        assigned_agent = None

        try:
            tasks_data = storage.load_tasks()
            task = next((t for t in tasks_data.tasks if t.id == task_id), None)
            if not task:
                logger.error(f"Tarefa {task_id} não encontrada para execução.")
                return

            workflows_data = storage.load_workflows()
            workflow = next((w for w in workflows_data.workflows if w.id == task.workflow_id), None)
            if not workflow:
                self.transition_state(task, TaskState.FAILED, reason=f"Workflow '{task.workflow_id}' não encontrado.")
                storage.save_tasks(tasks_data)
                await hub.broadcast({"type": "task.failed", "task_id": task.id, "error": "Workflow não encontrado"})
                return

            workspace = storage.load_workspace()
            squads_data = storage.load_squads()
            squad = next((s for s in squads_data.squads if s.id == task.squad_id), None) if task.squad_id else None

            # Transição inicial se estiver na fila
            if task.state == TaskState.QUEUED:
                self.transition_state(task, TaskState.IN_PROGRESS, reason="Início da execução do workflow")
                storage.save_tasks(tasks_data)
                await hub.broadcast({"type": "task.updated", "task": task.model_dump()})

            config = storage.load_config()
            llm = LLMClient(config)

            # Execução sequencial das etapas
            while task.current_step_index < len(workflow.steps):
                # Verificar se a tarefa foi pausada ou cancelada externamente
                if task.state in (TaskState.CANCELLED, TaskState.FAILED, TaskState.WAITING_APPROVAL):
                    break

                step = workflow.steps[task.current_step_index]
                logger.info(f"Executando etapa [{step.name}] para tarefa [{task.title}]")

                # Selecionar agente para a etapa
                assigned_agent = self.find_matching_agent(step.required_role, workspace, squad)
                if not assigned_agent:
                    self.transition_state(
                        task,
                        TaskState.FAILED,
                        reason=f"Nenhum agente disponível no escritório com o papel '{step.required_role}'."
                    )
                    storage.save_tasks(tasks_data)
                    await hub.broadcast({"type": "task.failed", "task_id": task.id, "error": "Sem agente disponível"})
                    break

                task.assigned_agent_id = assigned_agent.id

                # Notificar handoff do agente
                await hub.broadcast({
                    "event": "task.handoff",
                    "task_id": task.id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "payload": {
                        "step_id": step.id,
                        "step_name": step.name,
                        "agent_id": assigned_agent.id,
                        "agent_name": assigned_agent.name
                    }
                })
                await hub.broadcast_agent_status(assigned_agent.id, AgentState.WORKING)

                # Definir estado da tarefa conforme o tipo da etapa
                if step.action_type == WorkflowActionType.REVIEW:
                    self.transition_state(task, TaskState.QUALITY_GATE, reason=f"Iniciando quality gate: {step.name}")
                else:
                    if task.state != TaskState.IN_PROGRESS:
                        self.transition_state(task, TaskState.IN_PROGRESS, reason=f"Executando etapa: {step.name}")

                storage.save_tasks(tasks_data)
                await hub.broadcast({"type": "task.updated", "task": task.model_dump()})

                # Preparar prompt específico para o tipo de etapa
                if step.action_type == WorkflowActionType.REVIEW:
                    criteria_str = "\n".join(f"- {c}" for c in (step.review_criteria or ["Qualidade da solução", "Conformidade com requisitos"]))
                    step_prompt = (
                        f"Você é {assigned_agent.name}, atuando como {assigned_agent.title} (Revisor/QA).\n"
                        f"Tarefa: {task.title}\n"
                        f"Objetivo: {task.objective}\n\n"
                        f"Etapa de Revisão: {step.name}\n"
                        f"Critérios de Revisão Obrigatórios:\n{criteria_str}\n\n"
                        f"Instruções:\n{step.instructions}\n\n"
                    )
                    if task.decisions:
                        step_prompt += "Histórico e entregas anteriores:\n" + "\n".join(f"- {d}" for d in task.decisions) + "\n\n"
                    if task.artifacts:
                        step_prompt += "Artefatos propostos:\n" + "\n".join(f"- {a.name} ({a.file_path}):\n{a.diff or a.content or ''}" for a in task.artifacts) + "\n\n"
                    step_prompt += (
                        "Responda OBRIGATORIAMENTE no seguinte formato:\n"
                        "DECISÃO: [APROVADO ou REPROVADO]\n"
                        "CRITÉRIOS:\n<análise de cada critério>\n"
                        "FEEDBACK:\n<justificativa e orientações de correção se reprovado>\n"
                    )
                elif step.action_type == WorkflowActionType.PREPARE_CHANGE:
                    step_prompt = (
                        f"Você é {assigned_agent.name}, atuando como {assigned_agent.title}.\n"
                        f"Tarefa: {task.title}\n"
                        f"Objetivo: {task.objective}\n\n"
                        f"Etapa do Workflow: {step.name} (PREPARE_CHANGE)\n"
                        f"Instruções:\n{step.instructions}\n\n"
                    )
                    if task.decisions:
                        step_prompt += "Histórico de decisões anteriores:\n" + "\n".join(f"- {d}" for d in task.decisions) + "\n\n"
                    step_prompt += (
                        "IMPORTANTE: Proponha a alteração de arquivo no formato:\n"
                        "ARQUIVO_ALVO: <caminho relativo do arquivo>\n"
                        "RESUMO: <explicação concisa da alteração>\n"
                        "CONTEUDO_PROPOSTO:\n<conteúdo completo do arquivo modificado ou novo>\n"
                    )
                else:  # GENERATE
                    step_prompt = (
                        f"Você é {assigned_agent.name}, atuando como {assigned_agent.title}.\n"
                        f"Tarefa: {task.title}\n"
                        f"Objetivo: {task.objective}\n\n"
                        f"Etapa do Workflow: {step.name} (GENERATE)\n"
                        f"Instruções:\n{step.instructions}\n\n"
                    )
                    if task.decisions:
                        step_prompt += "Histórico de decisões anteriores:\n" + "\n".join(f"- {d}" for d in task.decisions) + "\n\n"

                # Executar chamada com timeout de 45 segundos
                try:
                    step_output = await llm.generate_response(
                        messages=[{"role": "user", "content": step_prompt}],
                        system_prompt=assigned_agent.system_prompt,
                        model_override=assigned_agent.model_name or None,
                        timeout=45.0
                    )
                except Exception as e:
                    logger.error(f"Falha ao executar etapa {step.name} com agente {assigned_agent.name}: {e}")
                    # Conforme regra 4.E: Se o revisor falhar ou exceder o timeout, marcar como FAILED
                    self.transition_state(
                        task,
                        TaskState.FAILED,
                        reason=f"Erro no provedor/modelo na etapa '{step.name}': {str(e)}"
                    )
                    storage.save_tasks(tasks_data)
                    await hub.broadcast({
                        "event": "task.failed",
                        "task_id": task.id,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "payload": {"error": str(e), "step_id": step.id}
                    })
                    break

                # -------------------------------------------------------------
                # TRATAMENTO POR TIPO DE AÇÃO
                # -------------------------------------------------------------

                # CASO 1: Etapa de Revisão (QUALITY GATE)
                if step.action_type == WorkflowActionType.REVIEW:
                    is_approved, feedback, criteria = self.evaluate_quality_gate(
                        step_output,
                        review_criteria=step.review_criteria
                    )

                    if not is_approved:
                        # Reprovação do Quality Gate
                        qg_payload = {
                            "step_id": step.id,
                            "step_name": step.name,
                            "result": "rejected",
                            "reviewer": assigned_agent.name,
                            "feedback": feedback[:300],
                            "revision_count": task.revision_count + 1,
                            "max_revisions": step.max_revisions
                        }
                        task.events.append(TaskEvent(
                            id=f"evt-{uuid.uuid4().hex[:8]}",
                            task_id=task.id,
                            event_type="task.quality_gate_event",
                            message=f"Quality gate reprovado por {assigned_agent.name} na etapa '{step.name}'",
                            timestamp=time.time(),
                            payload=qg_payload
                        ))
                        await hub.broadcast({
                            "event": "task.quality_gate_event",
                            "task_id": task.id,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "payload": qg_payload
                        })

                        # Verificar se o limite configurado de refações foi atingido
                        if task.revision_count >= step.max_revisions:
                            # Limite atingido: pausar a tarefa e solicitar intervenção humana
                            approval = ApprovalRequest(
                                id=f"appr-{uuid.uuid4().hex[:6]}",
                                task_id=task.id,
                                step_id=step.id,
                                summary=f"Limite de revisões ({step.max_revisions}) atingido na etapa de revisão '{step.name}'. Intervenção do usuário necessária.",
                                feedback=feedback,
                                status="pending",
                                created_at=time.time()
                            )
                            task.approvals.append(approval)
                            task.events.append(TaskEvent(
                                id=f"evt-{uuid.uuid4().hex[:8]}",
                                task_id=task.id,
                                event_type="task.approval_requested",
                                message=f"Intervenção solicitada: Limite de revisões atingido na etapa '{step.name}'",
                                timestamp=time.time(),
                                payload={"approval_id": approval.id, "summary": approval.summary}
                            ))
                            self.transition_state(
                                task,
                                TaskState.WAITING_APPROVAL,
                                reason=f"Limite de revisões ({step.max_revisions}) atingido em '{step.name}'. Aguardando decisão humana.",
                                payload={"approval_id": approval.id, "feedback": feedback}
                            )
                            storage.save_tasks(tasks_data)
                            await hub.broadcast({
                                "event": "task.approval_requested",
                                "task_id": task.id,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "payload": {
                                    "approval_id": approval.id,
                                    "summary": approval.summary,
                                    "feedback": feedback
                                }
                            })
                            await hub.broadcast({"type": "task.updated", "task": task.model_dump()})
                            break
                        else:
                            # Incrementa contador e devolve ao responsável pela etapa anterior
                            task.revision_count += 1
                            task.decisions.append(
                                f"[Revisão - {step.name}] REPROVADO por {assigned_agent.name} "
                                f"(Refação {task.revision_count}/{step.max_revisions}): {feedback[:200]}"
                            )
                            prev_step_index = max(0, task.current_step_index - 1)
                            task.current_step_index = prev_step_index
                            self.transition_state(
                                task,
                                TaskState.IN_PROGRESS,
                                reason=f"Revisão reprovada ({task.revision_count}/{step.max_revisions}). Devolvendo para refação na etapa '{workflow.steps[prev_step_index].name}'."
                            )
                            storage.save_tasks(tasks_data)
                            await hub.broadcast({"type": "task.updated", "task": task.model_dump()})
                            continue

                    else:
                        # Aprovação do Quality Gate
                        task.decisions.append(f"[Revisão - {step.name}] APROVADO por {assigned_agent.name}.")
                        qg_pass_payload = {
                            "step_id": step.id,
                            "step_name": step.name,
                            "result": "passed",
                            "reviewer": assigned_agent.name,
                            "feedback": feedback[:300]
                        }
                        task.events.append(TaskEvent(
                            id=f"evt-{uuid.uuid4().hex[:8]}",
                            task_id=task.id,
                            event_type="task.quality_gate_event",
                            message=f"Quality gate aprovado por {assigned_agent.name} na etapa '{step.name}'",
                            timestamp=time.time(),
                            payload=qg_pass_payload
                        ))
                        await hub.broadcast({
                            "event": "task.quality_gate_event",
                            "task_id": task.id,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "payload": qg_pass_payload
                        })

                        if step.requires_human_approval:
                            approval = ApprovalRequest(
                                id=f"appr-{uuid.uuid4().hex[:6]}",
                                task_id=task.id,
                                step_id=step.id,
                                summary=f"Revisão aprovada na etapa '{step.name}'. Confirmação humana requerida.",
                                status="pending",
                                created_at=time.time()
                            )
                            task.approvals.append(approval)
                            task.events.append(TaskEvent(
                                id=f"evt-{uuid.uuid4().hex[:8]}",
                                task_id=task.id,
                                event_type="task.approval_requested",
                                message=f"Confirmação humana requerida após revisão em '{step.name}'",
                                timestamp=time.time(),
                                payload={"approval_id": approval.id, "summary": approval.summary}
                            ))
                            self.transition_state(
                                task,
                                TaskState.WAITING_APPROVAL,
                                reason=f"Etapa {step.name} exige aprovação humana para avançar.",
                                payload={"approval_id": approval.id}
                            )
                            storage.save_tasks(tasks_data)
                            await hub.broadcast({
                                "event": "task.approval_requested",
                                "task_id": task.id,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "payload": {"approval_id": approval.id, "summary": approval.summary}
                            })
                            await hub.broadcast({"type": "task.updated", "task": task.model_dump()})
                            break
                        else:
                            task.current_step_index += 1
                            if task.current_step_index >= len(workflow.steps):
                                self.transition_state(
                                    task,
                                    TaskState.COMPLETED,
                                    reason="Todas as etapas do workflow foram finalizadas com sucesso."
                                )
                                self.generate_final_report(task)
                                task.events.append(TaskEvent(
                                    id=f"evt-{uuid.uuid4().hex[:8]}",
                                    task_id=task.id,
                                    event_type="task.completed",
                                    message="Todas as etapas do workflow foram finalizadas com sucesso.",
                                    timestamp=time.time(),
                                    payload={"total_steps": len(workflow.steps)}
                                ))
                                await hub.broadcast({
                                    "event": "task.completed",
                                    "task_id": task.id,
                                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "payload": {"total_steps": len(workflow.steps)}
                                })
                            else:
                                self.transition_state(
                                    task,
                                    TaskState.IN_PROGRESS,
                                    reason=f"Avançando para próxima etapa: {workflow.steps[task.current_step_index].name}"
                                )
                            storage.save_tasks(tasks_data)
                            await hub.broadcast({"type": "task.updated", "task": task.model_dump()})

                # CASO 2: Preparação de Alteração ou Requisito de Aprovação Humana
                elif step.action_type == WorkflowActionType.PREPARE_CHANGE or step.requires_human_approval:
                    affected_file, summary, proposed_content = self.parse_change_proposal(step_output)
                    diff_str = self.generate_unified_diff(affected_file, proposed_content, config.workspace_dir)

                    artifact_id = f"art-{uuid.uuid4().hex[:6]}"
                    artifact = TaskArtifact(
                        id=artifact_id,
                        name=f"Proposta da etapa {step.name}",
                        file_path=affected_file,
                        content_type="text/plain",
                        diff=diff_str,
                        content=proposed_content,
                        created_at=time.time()
                    )
                    task.artifacts.append(artifact)

                    approval = ApprovalRequest(
                        id=f"appr-{uuid.uuid4().hex[:6]}",
                        task_id=task.id,
                        step_id=step.id,
                        summary=summary or f"Proposta de alteração na etapa '{step.name}' por {assigned_agent.name}",
                        proposed_diff=diff_str,
                        proposed_content=proposed_content,
                        affected_file=affected_file,
                        status="pending",
                        created_at=time.time()
                    )
                    task.approvals.append(approval)

                    task.decisions.append(f"[{step.name}] Proposta gerada para '{affected_file}'. Aguardando aprovação humana.")
                    if not task.summary:
                        task.summary = summary

                    # Suspender a tarefa em WAITING_APPROVAL sem aplicar o arquivo
                    self.transition_state(
                        task,
                        TaskState.WAITING_APPROVAL,
                        reason=f"Etapa '{step.name}' gerou proposta de alteração que aguarda aprovação humana.",
                        payload={"approval_id": approval.id, "affected_file": affected_file}
                    )
                    storage.save_tasks(tasks_data)

                    await hub.broadcast({
                        "event": "task.approval_requested",
                        "task_id": task.id,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "payload": {
                            "approval_id": approval.id,
                            "summary": approval.summary,
                            "affected_file": approval.affected_file,
                            "proposed_diff": approval.proposed_diff
                        }
                    })
                    await hub.broadcast({"type": "task.updated", "task": task.model_dump()})
                    break

                # CASO 3: Etapa de Geração Padrão (GENERATE)
                else:
                    task.decisions.append(f"[{step.name}] Concluído por {assigned_agent.name}.")
                    if not task.summary:
                        task.summary = f"Execução de {step.name} concluída."

                    task.current_step_index += 1
                    if task.current_step_index >= len(workflow.steps):
                        self.transition_state(
                            task,
                            TaskState.COMPLETED,
                            reason="Todas as etapas do workflow foram finalizadas com sucesso."
                        )
                        self.generate_final_report(task)
                        await hub.broadcast({
                            "event": "task.completed",
                            "task_id": task.id,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "payload": {"total_steps": len(workflow.steps)}
                        })
                    else:
                        self.transition_state(
                            task,
                            TaskState.IN_PROGRESS,
                            reason=f"Avançando para próxima etapa: {workflow.steps[task.current_step_index].name}"
                        )

                    storage.save_tasks(tasks_data)
                    await hub.broadcast({"type": "task.updated", "task": task.model_dump()})

        finally:
            if assigned_agent:
                await hub.broadcast_agent_status(assigned_agent.id, AgentState.IDLE)
            self._running_tasks.discard(task_id)

    async def apply_approval_decision(
        self,
        task_id: str,
        approval_id: str,
        approved: bool,
        notes: Optional[str] = None,
        action: Optional[str] = None
    ) -> TaskPacket:
        """
        Aplica com segurança a decisão humana (aprovação ou recusa) sobre uma proposta de alteração.
        Garante verificação estrita de sandbox dentro do workspace antes de qualquer escrita.
        """
        tasks_data = storage.load_tasks()
        task = next((t for t in tasks_data.tasks if t.id == task_id), None)
        if not task:
            raise WorkflowEngineError(f"Tarefa '{task_id}' não encontrada.")

        approval = next((a for a in task.approvals if a.id == approval_id), None)
        if not approval:
            raise ApprovalNotFoundError(f"Aprovação '{approval_id}' não encontrada na tarefa '{task_id}'.")

        if approval.status != "pending":
            raise ApprovalAlreadyDecidedError(
                f"A solicitação de aprovação '{approval_id}' já foi decidida com status '{approval.status}'."
            )

        if task.state != TaskState.WAITING_APPROVAL:
            raise InvalidTransitionError(
                f"A tarefa está em '{task.state.value}'. Aprovações só podem ser decididas no estado WAITING_APPROVAL."
            )

        workflows_data = storage.load_workflows()
        workflow = next((w for w in workflows_data.workflows if w.id == task.workflow_id), None)

        if approved:
            # 1. Aplicação segura de arquivo se houver proposta
            if approval.affected_file and approval.proposed_content is not None:
                config = storage.load_config()
                workspace_dir = config.workspace_dir
                if not workspace_dir or not Path(workspace_dir).exists():
                    raise SecurityPathError(
                        "Pasta de trabalho (workspace_dir) não está configurada ou não existe. Impossível aplicar arquivos com segurança."
                    )

                is_safe = is_safe_workspace_child_path(approval.affected_file, workspace_dir)
                if not is_safe:
                    raise SecurityPathError(
                        f"Caminho inseguro detectado: '{approval.affected_file}'. Alteração rejeitada pelo sandbox."
                    )

                target_path = (Path(workspace_dir).resolve() / approval.affected_file).resolve()
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # Gravação atômica do arquivo aprovado
                tmp_target = target_path.with_name(f"{target_path.name}.tmp.{uuid.uuid4().hex[:6]}")
                try:
                    with open(tmp_target, "w", encoding="utf-8") as f:
                        f.write(approval.proposed_content)
                        f.flush()
                        os.fsync(f.fileno())
                    tmp_target.replace(target_path)
                except Exception as e:
                    if tmp_target.exists():
                        tmp_target.unlink(missing_ok=True)
                    raise WorkflowEngineError(f"Erro ao gravar arquivo aprovado: {e}")

            approval.status = "approved"
            approval.feedback = notes
            approval.decided_at = time.time()

            task.decisions.append(
                f"Proposta '{approval.summary}' APROVADA pelo usuário. "
                + (f"Arquivo '{approval.affected_file}' aplicado. " if approval.affected_file else "")
                + (f"Notas: {notes}" if notes else "")
            )

            approval_event = TaskEvent(
                id=f"evt-{uuid.uuid4().hex[:8]}",
                task_id=task.id,
                event_type="task.approved",
                message=f"Proposta aprovada pelo usuário: {approval.summary}",
                timestamp=time.time(),
                payload={
                    "approval_id": approval.id,
                    "affected_file": approval.affected_file,
                    "notes": notes
                }
            )
            task.events.append(approval_event)

            # Avançar para a próxima etapa do workflow
            task.current_step_index += 1
            if workflow and task.current_step_index < len(workflow.steps):
                self.transition_state(
                    task,
                    TaskState.IN_PROGRESS,
                    reason=f"Proposta aprovada. Continuando workflow na etapa '{workflow.steps[task.current_step_index].name}'."
                )
                storage.save_tasks(tasks_data)

                await hub.broadcast({
                    "event": "task.approved",
                    "task_id": task.id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "payload": {"approval_id": approval.id, "notes": notes}
                })
                await hub.broadcast({"type": "task.updated", "task": task.model_dump()})

                # Retomar a execução em background para continuar as próximas etapas
                asyncio.create_task(self.execute_task(task.id))
            else:
                self.transition_state(
                    task,
                    TaskState.COMPLETED,
                    reason="Proposta aprovada. Todas as etapas do workflow foram finalizadas com sucesso."
                )
                self.generate_final_report(task)
                storage.save_tasks(tasks_data)

                await hub.broadcast({
                    "event": "task.approved",
                    "task_id": task.id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "payload": {"approval_id": approval.id, "notes": notes}
                })
                await hub.broadcast({
                    "event": "task.completed",
                    "task_id": task.id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "payload": {"total_steps": len(workflow.steps) if workflow else 0}
                })
                await hub.broadcast({"type": "task.updated", "task": task.model_dump()})

            return task

        else:
            # Rejeição da proposta
            approval.status = "rejected"
            approval.feedback = notes
            approval.decided_at = time.time()

            task.decisions.append(
                f"Proposta '{approval.summary}' REJEITADA pelo usuário. "
                + (f"Justificativa: {notes}" if notes else "Sem justificativa")
            )

            reject_event = TaskEvent(
                id=f"evt-{uuid.uuid4().hex[:8]}",
                task_id=task.id,
                event_type="task.rejected",
                message=f"Proposta rejeitada pelo usuário: {approval.summary}",
                timestamp=time.time(),
                payload={
                    "approval_id": approval.id,
                    "notes": notes,
                    "action": action or "fail"
                }
            )
            task.events.append(reject_event)

            # Verificar se o usuário optou por refazer e há revisões disponíveis
            step = workflow.steps[task.current_step_index] if (workflow and task.current_step_index < len(workflow.steps)) else None
            max_revisions = step.max_revisions if step else 2

            if action == "retry" and task.revision_count < max_revisions:
                task.revision_count += 1
                self.transition_state(
                    task,
                    TaskState.IN_PROGRESS,
                    reason=f"Proposta rejeitada pelo usuário. Devolvendo para refação ({task.revision_count}/{max_revisions}). Justificativa: {notes or 'Nenhuma'}."
                )
                storage.save_tasks(tasks_data)

                await hub.broadcast({
                    "event": "task.rejected",
                    "task_id": task.id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "payload": {"approval_id": approval.id, "notes": notes, "action": "retry"}
                })
                await hub.broadcast({"type": "task.updated", "task": task.model_dump()})

                asyncio.create_task(self.execute_task(task.id))
                return task
            else:
                self.transition_state(
                    task,
                    TaskState.FAILED,
                    reason=f"Proposta de alteração rejeitada pelo usuário: {notes or 'Sem justificativa'}."
                )
                storage.save_tasks(tasks_data)

                await hub.broadcast({
                    "event": "task.rejected",
                    "task_id": task.id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "payload": {"approval_id": approval.id, "notes": notes, "action": "fail"}
                })
                await hub.broadcast({"type": "task.updated", "task": task.model_dump()})
                return task

    def generate_final_report(self, task: TaskPacket) -> Tuple[str, str]:
        """
        Gera relatório Markdown consolidado da tarefa concluída e salva no workspace.
        Garante que nenhuma chave de API, credencial ou raciocínio interno seja incluído.
        Retorna (clean_filename, markdown_content).
        """
        try:
            config = storage.load_config()
            workflows_data = storage.load_workflows()
            workflow = next((w for w in workflows_data.workflows if w.id == task.workflow_id), None)
            ws_data = storage.load_workspace()
            agents_map = {a.id: a for a in ws_data.agents}

            duration_sec = round(task.updated_at - task.created_at, 1)
            if duration_sec < 0:
                duration_sec = 0.0

            created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(task.created_at))
            updated_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(task.updated_at))

            # 1. Agentes envolvidos
            involved_agent_ids = set()
            if task.assigned_agent_id:
                involved_agent_ids.add(task.assigned_agent_id)
            for ev in task.events:
                if isinstance(ev.payload, dict) and ev.payload.get("agent_id"):
                    involved_agent_ids.add(ev.payload["agent_id"])

            agents_lines = []
            for aid in involved_agent_ids:
                ag = agents_map.get(aid)
                if ag:
                    agents_lines.append(f"- **{ag.name}** ({ag.title}) — Papel: `{ag.role_type}`")
                else:
                    agents_lines.append(f"- Agente ID: `{aid}`")
            if not agents_lines:
                agents_lines = ["- *Nenhum agente específico registrado.*"]

            # 2. Etapas executadas
            steps_lines = []
            if workflow and workflow.steps:
                for idx, st in enumerate(workflow.steps, 1):
                    is_done = idx <= (task.current_step_index + 1)
                    mark = "✅" if is_done else "⏳"
                    steps_lines.append(f"{idx}. {mark} **{st.name}** (`{st.action_type.value}`) — Papel: `{st.required_role}`")
            else:
                steps_lines = [f"- Etapas executadas (Total de passos: {task.current_step_index + 1})"]

            # 3. Arquivos criados ou modificados
            files_lines = []
            for art in task.artifacts:
                if art.file_path:
                    files_lines.append(f"- 📄 `{art.file_path}` — {art.name}")
            for app in task.approvals:
                if app.affected_file and app.status == "approved":
                    if not any(app.affected_file in fl for fl in files_lines):
                        files_lines.append(f"- ✏️ `{app.affected_file}` — Modificado com aprovação humana")
            if not files_lines:
                files_lines = ["- *Nenhum arquivo em disco foi criado ou modificado diretamente nesta tarefa.*"]

            # 4. Resultados de Quality Gates
            qg_lines = []
            qg_events = [e for e in task.events if e.event_type == "task.quality_gate_event"]
            if qg_events:
                for qe in qg_events:
                    payload = qe.payload if isinstance(qe.payload, dict) else {}
                    res = payload.get("result", "info")
                    icon = "✅ APROVADO" if res == "passed" else "❌ REPROVADO"
                    qg_lines.append(f"- {icon}: **Etapa '{payload.get('step_name', 'QA')}'** — {payload.get('feedback', qe.message)}")
            else:
                qg_lines = ["- *Nenhum Quality Gate foi executado explicitamente neste fluxo.*"]

            # 5. Aprovações e Recusas Humanas
            appr_lines = []
            if task.approvals:
                for ap in task.approvals:
                    status_label = "✅ APROVADO" if ap.status == "approved" else ("❌ REJEITADO" if ap.status == "rejected" else "⏳ PENDENTE")
                    notes = ap.feedback or getattr(ap, 'review_notes', None)
                    notes_part = f" (Notas: {notes})" if notes else ""
                    appr_lines.append(f"- **{status_label}**: {ap.summary}{notes_part}")
            else:
                appr_lines = ["- *Nenhuma ação exigiu aprovação humana neste fluxo.*"]

            # 6. Erros ou limitações encontrados
            errors_lines = []
            failed_events = [e for e in task.events if e.event_type == "task.failed"]
            if failed_events:
                for fe in failed_events:
                    errors_lines.append(f"- ⚠️ {fe.message}")
            if not errors_lines:
                errors_lines = ["- *Nenhum erro crítico ou falha durante a execução.*"]

            # Montagem estruturada do documento Markdown
            report_md = f"""# Relatório Final de Execução de Tarefa

**AgentOffice 2D — Orquestração de Workflows Multi-Agente**

---

## 1. Resumo da Tarefa
- **ID da Tarefa:** `{task.id}`
- **Título:** {task.title}
- **Objetivo:** {task.objective}
- **Workflow:** {workflow.name if workflow else task.workflow_id}
- **Status Final:** `{task.state.value}`
- **Criada em:** {created_str}
- **Finalizada em:** {updated_str}
- **Resumo do Trabalho:** {task.summary or "Workflow concluído com sucesso."}

---

## 2. Etapas Executadas
{chr(10).join(steps_lines)}

---

## 3. Agentes Envolvidos
{chr(10).join(agents_lines)}

---

## 4. Duração Total
- **Tempo total de execução:** {duration_sec} segundos
- **Ciclos de revisão / refação:** {task.revision_count}

---

## 5. Arquivos Criados ou Modificados
{chr(10).join(files_lines)}

---

## 6. Resultados dos Quality Gates
{chr(10).join(qg_lines)}

---

## 7. Aprovações e Recusas Humanas
{chr(10).join(appr_lines)}

---

## 8. Erros, Avisos ou Limitações
{chr(10).join(errors_lines)}

---
*Relatório gerado automaticamente pelo AgentOffice 2D. Credenciais de API e dados confidenciais são omitidos por segurança.*
"""
            clean_name = f"relatorio_tarefa_{task.id}.md"
            workspace_dir = Path(config.workspace_dir or str(BASE_DIR)).resolve()

            if is_safe_workspace_child_path(clean_name, str(workspace_dir)):
                workspace_dir.mkdir(parents=True, exist_ok=True)
                target_path = workspace_dir / clean_name
                target_path.write_text(report_md, encoding="utf-8")
                logger.info(f"Relatório final gravado com sucesso em: {target_path}")

            # Registra como artefato na tarefa se não existir
            if not any(a.file_path == clean_name for a in task.artifacts):
                task.artifacts.append(TaskArtifact(
                    id=f"art-rep-{uuid.uuid4().hex[:6]}",
                    name="Relatório Final de Execução",
                    file_path=clean_name,
                    content_type="text/markdown",
                    diff="",
                    content=report_md,
                    created_at=time.time()
                ))

            return clean_name, report_md

        except Exception as e:
            logger.error(f"Erro ao gerar relatório final da tarefa {task.id}: {e}")
            fallback_md = f"# Relatório da Tarefa {task.id}\nStatus: {task.state.value}\nErro ao gerar detalhes: {e}\n"
            return f"relatorio_tarefa_{task.id}.md", fallback_md

    def recover_interrupted_tasks(self) -> int:
        """
        Executado na inicialização: recupera tarefas que estavam no meio de execução
        quando o servidor reiniciou, marcando-as como falhas recuperáveis (FAILED) com registro de evento.
        """
        tasks_data = storage.load_tasks()
        recovered_count = 0

        for task in tasks_data.tasks:
            if task.state in (TaskState.IN_PROGRESS, TaskState.QUALITY_GATE):
                try:
                    self.transition_state(
                        task,
                        TaskState.FAILED,
                        reason="Execução interrompida por reinício do servidor. Recuperável pelo usuário."
                    )
                    recovered_count += 1
                except Exception as e:
                    logger.warning(f"Não foi possível recuperar tarefa {task.id}: {e}")

        if recovered_count > 0:
            storage.save_tasks(tasks_data, backup=False)
            logger.info(f"{recovered_count} tarefas interrompidas foram recuperadas como FAILED recuperável.")

        return recovered_count


# Instância global singleton do motor de workflow
workflow_engine = WorkflowEngine()
