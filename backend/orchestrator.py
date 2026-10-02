"""
AgentOffice 2D - Orchestrator
Orquestrador assíncrono para agentes autônomos, hierarquia Supervisor-Worker e delegação de tarefas.
Coordena animações físicas no Canvas e chamadas reais a modelos de IA.
"""

import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Optional

from backend.llm_client import LLMClient, LLMClientError
from backend.models import (
    Agent,
    AgentRoleType,
    AgentState,
    Desk,
    WorkspaceData,
)
from backend.storage import storage
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.orchestrator")


class Orchestrator:
    def __init__(self):
        pass

    async def execute_task(self, target_agent_id: str, user_prompt: str) -> None:
        """
        Ponto de entrada para executar uma tarefa enviada pelo usuário para um agente.
        Determina se o agente é Supervisor ou Worker/Solo e orquestra o fluxo correspondente.
        """
        workspace = storage.load_workspace()
        config = storage.load_config()
        llm = LLMClient(config)

        # Localizar o agente alvo
        agent = next((a for a in workspace.agents if a.id == target_agent_id), None)
        if not agent:
            await hub.broadcast_chat_error(target_agent_id, "Agente não encontrado no escritório.")
            return

        # Registrar a mensagem do usuário no histórico
        self._record_message(workspace, target_agent_id, "user", user_prompt)

        try:
            if agent.role_type == AgentRoleType.SUPERVISOR and agent.subordinate_ids:
                await self._execute_supervisor_workflow(agent, user_prompt, workspace, llm)
            else:
                await self._execute_direct_workflow(agent, user_prompt, workspace, llm)
        except Exception as e:
            logger.error(f"Erro na orquestração da tarefa: {e}", exc_info=True)
            await hub.broadcast_agent_status(agent.id, AgentState.IDLE)
            await hub.broadcast_chat_error(agent.id, f"Falha na execução: {str(e)}")

    async def _execute_direct_workflow(
        self,
        agent: Agent,
        user_prompt: str,
        workspace: WorkspaceData,
        llm: LLMClient
    ):
        """Execução direta para agentes Solo ou Workers chamados diretamente."""
        await hub.broadcast_agent_status(agent.id, AgentState.WORKING)
        await hub.broadcast_system_notice(f"{agent.name} ({agent.title}) iniciou o processamento...")

        history = self._get_conversation_context(workspace, agent.id)
        full_response = ""

        try:
            async for delta in llm.stream_response(
                messages=history,
                system_prompt=agent.system_prompt,
                model_override=agent.model_name or None
            ):
                full_response += delta
                await hub.broadcast_chat_delta(agent.id, delta)

            await hub.broadcast_chat_completed(agent.id, full_response)
            self._record_message(workspace, agent.id, "assistant", full_response)
        finally:
            await hub.broadcast_agent_status(agent.id, AgentState.IDLE)

    async def _execute_supervisor_workflow(
        self,
        supervisor: Agent,
        user_prompt: str,
        workspace: WorkspaceData,
        llm: LLMClient
    ):
        """
        Fluxo completo de delegação do Supervisor para Workers com movimentação no Canvas.
        """
        desks_map: Dict[str, Desk] = {d.id: d for d in workspace.desks}
        agents_map: Dict[str, Agent] = {a.id: a for a in workspace.agents}

        # Subordinados cadastrados
        subordinates: List[Agent] = [
            agents_map[sid] for sid in supervisor.subordinate_ids if sid in agents_map
        ]

        if not subordinates:
            # Caso não tenha subordinados disponíveis, responde diretamente
            await hub.broadcast_system_notice(
                f"{supervisor.name} não possui subordinados disponíveis no momento. Respondendo diretamente..."
            )
            await self._execute_direct_workflow(supervisor, user_prompt, workspace, llm)
            return

        # 1. Supervisor entra em estado THINKING
        await hub.broadcast_agent_status(supervisor.id, AgentState.THINKING)
        await hub.broadcast_system_notice(
            f"👑 {supervisor.name} está analisando o objetivo e planejando as subtarefas..."
        )

        # 2. Decomposição de tarefas pelo Supervisor
        plan = await self._decompose_task(supervisor, subordinates, user_prompt, llm)
        subtasks = plan.get("subtasks", [])
        plan_summary = plan.get("plan_summary", "Planejamento estruturado para a equipe.")

        await hub.broadcast_system_notice(f"📋 Plano do Tech Lead: {plan_summary}")
        await asyncio.sleep(1.0)

        # 3. Execução das subtarefas pelos Workers
        worker_reports = []
        supervisor_desk = desks_map.get(supervisor.desk_id)

        for item in subtasks:
            worker_id = item.get("worker_id")
            task_desc = item.get("task", "")
            worker = agents_map.get(worker_id)
            if not worker:
                continue

            worker_desk = desks_map.get(worker.desk_id)

            # Notificar início da tarefa do Worker
            await hub.broadcast_agent_status(worker.id, AgentState.WORKING)
            await hub.broadcast_system_notice(
                f"⚙️ {worker.name} ({worker.title}) assumiu a subtarefa: \"{task_desc[:60]}...\""
            )

            # Worker executa a inferência com o modelo
            worker_prompt = f"Você é {worker.title}. Execute a seguinte subtarefa solicitada pelo seu Tech Lead ({supervisor.name}):\n\n{task_desc}\n\nForneça uma resposta detalhada e objetiva."
            worker_output = await llm.generate_response(
                messages=[{"role": "user", "content": worker_prompt}],
                system_prompt=worker.system_prompt,
                model_override=worker.model_name or None,
                timeout=45.0
            )

            # Animação física: Worker caminha até a mesa do supervisor
            if worker_desk and supervisor_desk:
                # 3a. Caminha até a frente da mesa do Supervisor
                await hub.broadcast_agent_status(worker.id, AgentState.WALKING)
                await hub.broadcast_agent_move(
                    agent_id=worker.id,
                    target_x=supervisor_desk.front_x,
                    target_y=supervisor_desk.front_y,
                    action="walk_to_supervisor",
                    speed=2.5
                )
                await hub.broadcast_system_notice(
                    f"🚶 {worker.name} está levando o relatório até a mesa de {supervisor.name}..."
                )
                # Tempo para a animação física transcorrer
                await asyncio.sleep(2.0)

                # 3b. Entrega o relatório (estado REPORTING com balão)
                await hub.broadcast_agent_status(worker.id, AgentState.REPORTING)
                await hub.broadcast_system_notice(
                    f"📄 {worker.name} entregou o relatório técnico para {supervisor.name}!"
                )
                await asyncio.sleep(1.8)

                # 3c. Retorna para o próprio assento
                await hub.broadcast_agent_status(worker.id, AgentState.WALKING)
                await hub.broadcast_agent_move(
                    agent_id=worker.id,
                    target_x=worker_desk.seat_x,
                    target_y=worker_desk.seat_y,
                    action="return_to_desk",
                    speed=2.5
                )
                await asyncio.sleep(1.8)
                await hub.broadcast_agent_status(worker.id, AgentState.IDLE)

            worker_reports.append({
                "worker_name": worker.name,
                "worker_title": worker.title,
                "task": task_desc,
                "result": worker_output
            })

        # 4. Supervisor consolida todas as entregas e transmite resposta final
        await hub.broadcast_agent_status(supervisor.id, AgentState.WORKING)
        await hub.broadcast_system_notice(
            f"👑 {supervisor.name} está consolidando todas as entregas dos subordinados..."
        )

        consolidation_prompt = (
            f"Você é {supervisor.name}, {supervisor.title}. O usuário fez a seguinte solicitação:\n"
            f"\"{user_prompt}\"\n\n"
            f"Sua equipe de subordinados realizou as seguintes entregas técnicas:\n"
        )
        for r in worker_reports:
            consolidation_prompt += (
                f"\n--- Relatório de {r['worker_name']} ({r['worker_title']}) ---\n"
                f"Subtarefa: {r['task']}\n"
                f"Resultado:\n{r['result']}\n"
            )

        consolidation_prompt += (
            "\n\nCom base em todas as entregas acima, forneça a resposta final executiva e integrada para o usuário. "
            "Reconheça brevemente a colaboração dos membros da equipe e sintetize a solução de forma brilhante."
        )

        full_final_response = ""
        async for delta in llm.stream_response(
            messages=[{"role": "user", "content": consolidation_prompt}],
            system_prompt=supervisor.system_prompt,
            model_override=supervisor.model_name or None
        ):
            full_final_response += delta
            await hub.broadcast_chat_delta(supervisor.id, delta)

        await hub.broadcast_chat_completed(supervisor.id, full_final_response)
        self._record_message(workspace, supervisor.id, "assistant", full_final_response)
        await hub.broadcast_agent_status(supervisor.id, AgentState.IDLE)
        await hub.broadcast_system_notice(f"✨ Tarefa concluída com sucesso pela equipe de {supervisor.name}!")

    async def _decompose_task(
        self,
        supervisor: Agent,
        subordinates: List[Agent],
        user_prompt: str,
        llm: LLMClient
    ) -> dict:
        """Usa o modelo de IA do Supervisor para decompor a tarefa em formato JSON."""
        workers_desc = "\n".join(
            f"- ID: \"{w.id}\", Nome: {w.name}, Cargo: {w.title}, Perfil: {w.system_prompt[:80]}"
            for w in subordinates
        )

        planner_system = (
            f"Você é {supervisor.name}, {supervisor.title} no AgentOffice 2D.\n"
            "Sua missão é decompor o objetivo do usuário em subtarefas específicas para seus subordinados.\n"
            "Responda ESTRITAMENTE em formato JSON com o seguinte schema:\n"
            "{\n"
            '  "plan_summary": "Resumo em uma frase do plano",\n'
            '  "subtasks": [\n'
            '    {\n'
            '      "worker_id": "ID_DO_SUBORDINADO",\n'
            '      "task": "Descrição detalhada do que o subordinado deve fazer"\n'
            '    }\n'
            '  ]\n'
            "}\n\n"
            f"Subordinados disponíveis sob sua liderança:\n{workers_desc}"
        )

        raw = await llm.generate_response(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=planner_system,
            model_override=supervisor.model_name or None,
            json_mode=True,
            timeout=30.0
        )

        return self._extract_json(raw, subordinates)

    def _extract_json(self, raw_text: str, subordinates: List[Agent]) -> dict:
        """Extrai e valida o JSON do plano gerado pelo LLM com tolerância a formatações."""
        try:
            # Tentar direto
            return json.loads(raw_text)
        except Exception:
            pass

        # Buscar bloco markdown ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        # Buscar o primeiro par de chaves { ... }
        match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        # Fallback inteligente: atribui subtarefa a cada subordinado
        logger.warning(f"Não foi possível decodificar JSON direto: {raw_text[:120]}. Usando plano de fallback.")
        return {
            "plan_summary": "Coordenação distribuída entre os membros da equipe.",
            "subtasks": [
                {
                    "worker_id": sub.id,
                    "task": f"Analise e contribua com sua especialidade ({sub.title}) para a demanda solicitada."
                }
                for sub in subordinates
            ]
        }

    def _record_message(self, workspace: WorkspaceData, agent_id: str, role: str, text: str):
        if agent_id not in workspace.conversations:
            workspace.conversations[agent_id] = []
        workspace.conversations[agent_id].append({
            "sender": agent_id if role == "assistant" else "user",
            "role": role,
            "text": text,
            "timestamp": time.time()
        })
        storage.save_workspace(workspace, backup=False)

    def _get_conversation_context(self, workspace: WorkspaceData, agent_id: str) -> List[Dict[str, str]]:
        convs = workspace.conversations.get(agent_id, [])
        # Últimas 10 mensagens
        return [
            {"role": m["role"], "content": m["text"]}
            for m in convs[-10:]
            if m.get("role") in ("user", "assistant")
        ]


# Singleton
orchestrator = Orchestrator()
