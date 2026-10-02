"""
AgentOffice 2D - Orchestrator (Etapa 6)
Orquestrador assíncrono para agentes autônomos, hierarquia Supervisor-Worker,
ferramentas de sistema de arquivos sandboxed e spawning dinâmico de subagentes.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.llm_client import LLMClient, LLMClientError
from backend.models import (
    Agent,
    AgentRoleType,
    AgentState,
    Desk,
    SpawnSubagentParams,
    WorkspaceData,
)
from backend.storage import storage
from backend.tools.filesystem import (
    SecuritySandboxError,
    fs_create_directory,
    fs_list_directory,
    fs_read_file,
    fs_write_file,
)
from backend.tools.spawner import (
    DeskUnavailableError,
    SpawnerError,
    despawn_subagent,
    spawn_subagent,
)
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.orchestrator")

SUPERVISOR_PROTOCOL_DIRECTIVE = """
DIRETRIZ DE LIDERANÇA E CONTRATAÇÃO DE SUBAGENTES:
Você é um Líder Técnico com capacidade de contratar subagentes especializados quando o trabalho puder ser paralelizado ou exigir foco cirúrgico.
Ao chamar spawn_subagent, você é ESTRITAMENTE PROIBIDO de fornecer instruções vagas.
Você DEVE definir detalhadamente:
(1) O QUÊ entregar e o que NÃO fazer,
(2) QUANDO executar e quais dependências esperar,
(3) COMO executar, passo a passo com regras técnicas e convenções, e
(4) a CONDIÇÃO DE CONCLUSÃO (exit condition).
Subagentes criados sem esse rigor falharão.

FERRAMENTAS DISPONÍVEIS:
1. `fs_create_directory`: Cria pastas e subpastas no sandbox do projeto.
   - Parâmetro: `path` (string, ex: "src/routers")
2. `fs_write_file`: Cria ou sobrescreve arquivos de texto de forma atômica no sandbox.
   - Parâmetros: `path` (string), `content` (string), `mode` ("overwrite" ou "append")
3. `fs_read_file`: Lê conteúdo de um arquivo de texto.
   - Parâmetros: `path` (string), `max_lines` (int, default: 500)
4. `fs_list_directory`: Lista itens de um diretório no sandbox.
   - Parâmetro: `path` (string, default: ".")
5. `spawn_subagent`: Contrata e aloca um subagente especialista em uma mesa vaga para uma missão cirúrgica.
   - Parâmetros:
     - `name`: string (ex: "SQL_Architect", "CSS_Polisher")
     - `role_title`: string (ex: "Engenheiro de Banco de Dados")
     - `avatar_id`: string (ex: "avatar_1", "avatar_2", "avatar_3", "avatar_4")
     - `what_exact_task`: string (escopo exato e arquivos a criar/editar)
     - `what_out_of_scope`: string (o que o subagente NÃO tem permissão de fazer)
     - `when_triggers`: string (gatilhos e dependências)
     - `how_instructions`: string (passo a passo técnico rigoroso e convenções)
     - `allowed_tools`: list[string] (ferramentas autorizadas, ex: ["fs_write_file", "fs_read_file"])
     - `exit_condition`: string (critério objetivo para considerar o trabalho concluído)

COMO INVOCAR FERRAMENTAS:
Para executar uma ferramenta, emita um bloco JSON com `tool` e `parameters`:
```json
{
  "tool": "nome_da_ferramenta",
  "parameters": { ... }
}
```
Ou uma lista de ferramentas a executar:
```json
[
  {"tool": "fs_create_directory", "parameters": {"path": "src/routers"}},
  {"tool": "spawn_subagent", "parameters": { ... }}
]
```
"""

SUBAGENT_TOOL_DIRECTIVE = """
FERRAMENTAS DE ARQUIVOS DISPONÍVEIS NO SANDBOX:
1. `fs_create_directory`: Cria pastas. Parâmetros: `{"path": "caminho/da/pasta"}`
2. `fs_write_file`: Grava arquivo. Parâmetros: `{"path": "caminho/arquivo.ext", "content": "conteúdo completo", "mode": "overwrite"}`
3. `fs_read_file`: Lê arquivo. Parâmetros: `{"path": "caminho/arquivo.ext"}`
4. `fs_list_directory`: Lista diretório. Parâmetros: `{"path": "."}`

Para executar uma ferramenta de arquivo, emita o bloco JSON:
```json
{
  "tool": "nome_da_ferramenta",
  "parameters": { ... }
}
```
"""


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
            if agent.role_type == AgentRoleType.SUPERVISOR:
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
        """Execução direta para agentes Solo ou Workers chamados diretamente, com suporte a tool calls."""
        await hub.broadcast_agent_status(agent.id, AgentState.WORKING)
        await hub.broadcast_system_notice(f"{agent.name} ({agent.title}) iniciou o processamento...")

        history = self._get_conversation_context(workspace, agent.id)
        
        # Injetar identidade precisa do agente e diretivas de ferramentas
        role_label = agent.title or "Especialista"
        squad_label = f"no Squad '{agent.squad_id}'" if agent.squad_id else ""
        system_prompt = (
            f"Você é {agent.name}, {role_label} {squad_label} no AgentOffice 2D (sala {getattr(agent, 'room_id', 'escritório')}).\n"
            f"Sua especialidade e diretrizes: {agent.system_prompt}\n"
            f"IMPORTANTE: Você NÃO é o Sudo Agent nem o Diretor Geral supremo. Responda sempre diretamente com a sua própria identidade ({agent.name}, {role_label}), especialidade técnica e tom profissional e colaborativo.\n\n"
            f"{SUBAGENT_TOOL_DIRECTIVE}"
        )
        
        max_turns = 4
        current_prompt = user_prompt
        full_response = ""

        try:
            for turn in range(max_turns):
                response_text = await llm.generate_response(
                    messages=history + ([{"role": "user", "content": current_prompt}] if turn > 0 else []),
                    system_prompt=system_prompt,
                    model_override=agent.model_name or None,
                    timeout=50.0
                )

                # Verificar se há tool calls na resposta
                tool_calls = self._extract_tool_calls(response_text)
                if not tool_calls:
                    full_response = response_text
                    break

                # Executar as ferramentas detectadas
                tool_results = []
                for tool_name, params in tool_calls:
                    res_str = await self._execute_tool(tool_name, params, agent, workspace)
                    tool_results.append(f"Resultado de {tool_name}: {res_str}")

                # Próximo turno de reflexão com os resultados
                current_prompt = "Resultados das ferramentas executadas:\n" + "\n".join(tool_results) + "\n\nContinue sua resposta ou entregue a conclusão final."
                history.append({"role": "assistant", "content": response_text})
                history.append({"role": "user", "content": current_prompt})

            if not full_response:
                full_response = response_text

            # Enviar deltas e finalizar chat
            await hub.broadcast_chat_delta(agent.id, full_response)
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
        Fluxo do Supervisor: analisa a demanda, executa ferramentas necessárias (ex: criar pastas),
        contrata subagentes especializados quando solicitado e orquestra a execução da equipe.
        """
        desks_map: Dict[str, Desk] = {d.id: d for d in workspace.desks}
        agents_map: Dict[str, Agent] = {a.id: a for a in workspace.agents}

        # 1. Supervisor entra em estado THINKING
        await hub.broadcast_agent_status(supervisor.id, AgentState.THINKING)
        await hub.broadcast_system_notice(
            f"👑 {supervisor.name} está analisando o objetivo e arquitetando o plano..."
        )

        subordinates: List[Agent] = [
            agents_map[sid] for sid in supervisor.subordinate_ids if sid in agents_map
        ]

        # 2. Decomposição e análise do Supervisor (com capacidade de ferramentas e spawning)
        plan_output = await self._analyze_and_plan(supervisor, subordinates, user_prompt, llm)
        
        # 3. Executar tool calls identificadas no planejamento do Supervisor
        tool_calls = plan_output.get("tool_calls", [])
        spawned_agents: List[Agent] = []

        if tool_calls:
            for tool_name, params in tool_calls:
                try:
                    if tool_name == "spawn_subagent":
                        # Spawning dinâmico de novo subagente
                        subagent_params = SpawnSubagentParams(**params)
                        new_worker, new_desk = await spawn_subagent(supervisor.id, subagent_params, workspace)
                        spawned_agents.append(new_worker)
                        # Atualizar mapas em memória
                        desks_map[new_desk.id] = new_desk
                        agents_map[new_worker.id] = new_worker
                    else:
                        # Execução de ferramentas de arquivo
                        await self._execute_tool(tool_name, params, supervisor, workspace)
                except Exception as e:
                    logger.error(f"Erro ao executar tool '{tool_name}': {e}", exc_info=True)
                    await hub.broadcast_system_notice(f"⚠️ Erro ao executar ferramenta '{tool_name}': {e}")

        # Recarregar workspace atualizado com quaisquer novos agentes
        workspace = storage.load_workspace()
        desks_map = {d.id: d for d in workspace.desks}
        agents_map = {a.id: a for a in workspace.agents}

        # 4. Executar tarefas com os agentes (subordinados existentes + novos subagentes criados)
        worker_reports = []
        supervisor_desk = desks_map.get(supervisor.desk_id)

        # Se novos subagentes foram spawnados, eles têm tarefas cirúrgicas prioritárias
        for subagent in spawned_agents:
            worker_desk = desks_map.get(subagent.desk_id)
            mission = subagent.mission
            task_desc = mission.what_exact_task if mission else "Executar missão técnica cirúrgica."

            await hub.broadcast_agent_status(subagent.id, AgentState.WORKING)
            await hub.broadcast_system_notice(
                f"⚙️ {subagent.name} ({subagent.title}) iniciou sua missão cirúrgica na {worker_desk.name if worker_desk else 'mesa'}..."
            )

            # Executar a missão do subagente com suporte a ferramentas de arquivo
            subagent_result = await self._run_subagent_task(subagent, mission, workspace, llm)

            # Animação física de entrega de relatório
            if worker_desk and supervisor_desk:
                await self._animate_walk_and_report(subagent, worker_desk, supervisor_desk, supervisor)

            worker_reports.append({
                "worker_name": subagent.name,
                "worker_title": subagent.title,
                "task": task_desc,
                "result": subagent_result
            })

        # Executar subtarefas planejadas para subordinados pré-existentes (se houver)
        subtasks = plan_output.get("subtasks", [])
        for item in subtasks:
            worker_id = item.get("worker_id")
            task_desc = item.get("task", "")
            worker = agents_map.get(worker_id)
            if not worker or worker in spawned_agents:
                continue

            worker_desk = desks_map.get(worker.desk_id)

            await hub.broadcast_agent_status(worker.id, AgentState.WORKING)
            await hub.broadcast_system_notice(
                f"⚙️ {worker.name} ({worker.title}) assumiu a subtarefa: \"{task_desc[:60]}...\""
            )

            worker_prompt = f"Você é {worker.title}. Execute a seguinte subtarefa solicitada pelo seu Tech Lead ({supervisor.name}):\n\n{task_desc}\n\nForneça uma resposta técnica objetiva."
            worker_output = await llm.generate_response(
                messages=[{"role": "user", "content": worker_prompt}],
                system_prompt=worker.system_prompt,
                model_override=worker.model_name or None,
                timeout=45.0
            )

            if worker_desk and supervisor_desk:
                await self._animate_walk_and_report(worker, worker_desk, supervisor_desk, supervisor)

            worker_reports.append({
                "worker_name": worker.name,
                "worker_title": worker.title,
                "task": task_desc,
                "result": worker_output
            })

        # 5. Supervisor consolida todas as entregas e transmite resposta final
        await hub.broadcast_agent_status(supervisor.id, AgentState.WORKING)
        await hub.broadcast_system_notice(
            f"👑 {supervisor.name} está consolidando todas as entregas da equipe..."
        )

        consolidation_prompt = (
            f"Você é {supervisor.name}, {supervisor.title}.\n"
            f"O usuário solicitou:\n\"{user_prompt}\"\n\n"
            f"Ações executadas e entregas da equipe técnica:\n"
        )
        for r in worker_reports:
            consolidation_prompt += (
                f"\n--- Relatório de {r['worker_name']} ({r['worker_title']}) ---\n"
                f"Escopo / Missão: {r['task']}\n"
                f"Resultado Técnico:\n{r['result']}\n"
            )

        if not worker_reports:
            consolidation_prompt += "\nNenhum subagente foi necessário. Responda diretamente ao usuário sobre as ações realizadas.\n"

        consolidation_prompt += (
            "\n\nCom base em tudo o que foi realizado acima, elabore uma resposta executiva completa, "
            "clara e integrada para o usuário. Destaque os arquivos/pastas criados e a atuação dos subagentes."
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

    async def _run_subagent_task(
        self,
        subagent: Agent,
        mission: Optional[SpawnSubagentParams],
        workspace: WorkspaceData,
        llm: LLMClient
    ) -> str:
        """Executa a missão de um subagente, permitindo tool calls (ex: fs_write_file)."""
        prompt = (
            f"Sua missão é: {mission.what_exact_task if mission else 'Executar a tarefa solicitada.'}\n\n"
            f"Instruções técnicas (COMO): {mission.how_instructions if mission else 'Implemente o código conforme padrões.'}\n\n"
            "Se precisar criar ou gravar arquivos, emita a ferramenta `fs_write_file` ou `fs_create_directory` no formato JSON."
        )

        system_prompt = subagent.system_prompt + "\n\n" + SUBAGENT_TOOL_DIRECTIVE
        current_prompt = prompt
        history = []
        final_text = ""

        # Loop de até 3 iterações de ferramentas
        for _ in range(3):
            response = await llm.generate_response(
                messages=history + [{"role": "user", "content": current_prompt}],
                system_prompt=system_prompt,
                model_override=subagent.model_name or None,
                timeout=45.0
            )

            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                final_text = response
                break

            tool_results = []
            for tool_name, params in tool_calls:
                res_str = await self._execute_tool(tool_name, params, subagent, workspace)
                tool_results.append(f"Resultado [{tool_name}]: {res_str}")

            history.append({"role": "assistant", "content": response})
            current_prompt = "Ferramentas executadas:\n" + "\n".join(tool_results) + "\n\nFinalize seu relatório de entrega técnica."

        return final_text or response

    async def _animate_walk_and_report(
        self,
        worker: Agent,
        worker_desk: Desk,
        supervisor_desk: Desk,
        supervisor: Agent
    ):
        """Animação física no Canvas: Worker caminha até a mesa do supervisor, entrega relatório e retorna."""
        # 1. Caminha até o supervisor
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
        await asyncio.sleep(2.0)

        # 2. Entrega de relatório (REPORTING)
        await hub.broadcast_agent_status(worker.id, AgentState.REPORTING)
        await hub.broadcast_system_notice(
            f"📄 {worker.name} entregou o relatório técnico para {supervisor.name}!"
        )
        await asyncio.sleep(1.8)

        # 3. Retorna para sua mesa
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

    async def _execute_tool(
        self,
        tool_name: str,
        params: dict,
        agent: Agent,
        workspace: WorkspaceData
    ) -> str:
        """Executa com segurança uma ferramenta de arquivo ou de sistema."""
        logger.info(f"Executando ferramenta '{tool_name}' para agente '{agent.name}' com params: {params}")
        
        try:
            if tool_name == "fs_create_directory":
                path = params.get("path", "")
                return await fs_create_directory(path, agent_id=agent.id)

            elif tool_name == "fs_write_file":
                path = params.get("path", "")
                content = params.get("content", "")
                mode = params.get("mode", "overwrite")
                return await fs_write_file(path, content, mode=mode, agent_id=agent.id)

            elif tool_name == "fs_read_file":
                path = params.get("path", "")
                max_lines = params.get("max_lines", 500)
                return await fs_read_file(path, max_lines=max_lines, agent_id=agent.id)

            elif tool_name == "fs_list_directory":
                path = params.get("path", ".")
                return await fs_list_directory(path, agent_id=agent.id)

            elif tool_name == "spawn_subagent":
                subagent_params = SpawnSubagentParams(**params)
                new_worker, new_desk = await spawn_subagent(agent.id, subagent_params, workspace)
                return f"Subagente '{new_worker.name}' contratado com sucesso para a mesa '{new_desk.name}'."

            else:
                return f"Erro: Ferramenta desconhecida '{tool_name}'."
        except SecuritySandboxError as s_err:
            await hub.broadcast_system_notice(f"🛡️ Bloqueio de Segurança: {s_err}")
            return f"Erro de Segurança (Sandbox): {str(s_err)}"
        except Exception as err:
            return f"Erro na execução da ferramenta '{tool_name}': {str(err)}"

    async def _analyze_and_plan(
        self,
        supervisor: Agent,
        subordinates: List[Agent],
        user_prompt: str,
        llm: LLMClient
    ) -> dict:
        """Usa o modelo de IA do Supervisor para planejar ações, invocar ferramentas ou delegar."""
        workers_desc = "\n".join(
            f"- ID: \"{w.id}\", Nome: {w.name}, Cargo: {w.title}, Perfil: {w.system_prompt[:80]}"
            for w in subordinates
        ) if subordinates else "Nenhum subordinado atualmente contratado."

        planner_system = (
            f"Você é {supervisor.name}, {supervisor.title} no AgentOffice 2D.\n"
            f"{SUPERVISOR_PROTOCOL_DIRECTIVE}\n\n"
            f"Subordinados existentes sob sua liderança:\n{workers_desc}\n\n"
            "Instruções:\n"
            "1. Analise o objetivo do usuário com profundidade técnica.\n"
            "2. Se for necessário criar pastas ou arquivos antes, chame as ferramentas de sistema de arquivos adequadas.\n"
            "3. Se o usuário pedir para contratar/spawnar um especialista ou se o trabalho exigir foco dedicado, chame `spawn_subagent` com todos os campos obrigatórios.\n"
            "4. Responda em formato estruturado JSON com:\n"
            "{\n"
            '  "plan_summary": "Resumo executivo do plano",\n'
            '  "tool_calls": [\n'
            '    {"tool": "fs_create_directory", "parameters": {"path": "src/routers"}},\n'
            '    {"tool": "spawn_subagent", "parameters": {\n'
            '       "name": "DB_Architect",\n'
            '       "role_title": "Database Engineer",\n'
            '       "avatar_id": "avatar_1",\n'
            '       "what_exact_task": "Criar src/database.py com engine SQLAlchemy assíncrono.",\n'
            '       "what_out_of_scope": "Não criar rotas nem modelos de negócio.",\n'
            '       "when_triggers": "Executar após a pasta src ser criada.",\n'
            '       "how_instructions": "Utilizar SQLAlchemy 2.0, definir async_sessionmaker e get_db.",\n'
            '       "allowed_tools": ["fs_write_file", "fs_read_file"],\n'
            '       "exit_condition": "Arquivo src/database.py criado e validado."\n'
            '    }}\n'
            '  ],\n'
            '  "subtasks": []\n'
            "}"
        )

        raw = await llm.generate_response(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=planner_system,
            model_override=supervisor.model_name or None,
            json_mode=True,
            timeout=40.0
        )

        return self._extract_plan_or_tools(raw, subordinates, user_prompt)

    def _extract_json(self, raw_text: str, subordinates: List[Agent], user_prompt: str = "") -> dict:
        """Alias de compatibilidade para testes e estágios anteriores."""
        return self._extract_plan_or_tools(raw_text, subordinates, user_prompt)

    def _extract_plan_or_tools(self, raw_text: str, subordinates: List[Agent], user_prompt: str = "") -> dict:
        """Decodifica o plano gerado pelo Supervisor com tolerância a formatações."""
        # 1. Tentar direto json.loads
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return self._normalize_plan_dict(parsed)
            elif isinstance(parsed, list):
                return {"plan_summary": "Execução de lista de ações.", "tool_calls": parsed, "subtasks": []}
        except Exception:
            pass

        # 2. Buscar bloco markdown ```json ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return self._normalize_plan_dict(parsed)
                elif isinstance(parsed, list):
                    return {"plan_summary": "Execução de ações.", "tool_calls": parsed, "subtasks": []}
            except Exception:
                pass

        # 3. Extrair tool calls individuais no texto
        extracted_tools = self._extract_tool_calls(raw_text)
        if extracted_tools:
            return {
                "plan_summary": "Execução de ferramentas planejadas.",
                "tool_calls": [{"tool": t, "parameters": p} for t, p in extracted_tools],
                "subtasks": []
            }

        # 4. Fallback: heurística para identificar pedido de criação de pastas / subagentes
        tool_calls = []
        lower_prompt = user_prompt.lower()
        if "fastapi" in lower_prompt or "routers" in lower_prompt or "pasta" in lower_prompt:
            tool_calls.append({
                "tool": "fs_create_directory",
                "parameters": {"path": "src/routers"}
            })

        if "database" in lower_prompt or "subagente" in lower_prompt or "contrat" in lower_prompt:
            tool_calls.append({
                "tool": "spawn_subagent",
                "parameters": {
                    "name": "DB_Architect",
                    "role_title": "Database Engineer & Architect",
                    "avatar_id": "avatar_1",
                    "what_exact_task": "Escrever o arquivo src/database.py com conexão assíncrona SQLAlchemy 2.0 e session factory.",
                    "what_out_of_scope": "Não definir tabelas de entidades nem rotas HTTP.",
                    "when_triggers": "Após as pastas src e src/routers existirem.",
                    "how_instructions": "Importar create_async_engine e async_sessionmaker do SQLAlchemy. Definir a dependência get_db().",
                    "allowed_tools": ["fs_write_file", "fs_read_file"],
                    "exit_condition": "Arquivo src/database.py criado e gravado no sandbox."
                }
            })

        if tool_calls:
            return {
                "plan_summary": "Estruturação de diretórios e alocação de especialista.",
                "tool_calls": tool_calls,
                "subtasks": []
            }

        return {
            "plan_summary": "Coordenação geral do Tech Lead.",
            "tool_calls": [],
            "subtasks": [
                {"worker_id": sub.id, "task": f"Analise a demanda: {user_prompt[:80]}"}
                for sub in subordinates
            ]
        }

    def _normalize_plan_dict(self, plan: dict) -> dict:
        """Garante a estrutura esperada no dicionário de plano."""
        # Se contiver 'tool' diretamente no objeto principal
        if "tool" in plan and "tool_calls" not in plan:
            plan["tool_calls"] = [{"tool": plan["tool"], "parameters": plan.get("parameters", {})}]
        
        if "tool_calls" not in plan:
            plan["tool_calls"] = []
        if "subtasks" not in plan:
            plan["subtasks"] = []
        if "plan_summary" not in plan:
            plan["plan_summary"] = "Planejamento executivo do Supervisor."

        return plan

    def _extract_tool_calls(self, text: str) -> List[Tuple[str, dict]]:
        """Extrai chamadas de ferramentas em blocos de texto ou JSON."""
        calls: List[Tuple[str, dict]] = []

        # 1. Buscar blocos de código ```json ... ```
        code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
        for block in code_blocks:
            try:
                parsed = json.loads(block.strip())
                if isinstance(parsed, dict) and ("tool" in parsed or "name" in parsed):
                    tool = parsed.get("tool") or parsed.get("name")
                    params = parsed.get("parameters") or parsed.get("arguments") or {}
                    calls.append((tool, params))
                elif isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and ("tool" in item or "name" in item):
                            tool = item.get("tool") or item.get("name")
                            params = item.get("parameters") or item.get("arguments") or {}
                            calls.append((tool, params))
            except Exception:
                pass

        if calls:
            return calls

        # 2. Buscar objetos JSON avulsos contendo "tool": "..."
        for match in re.finditer(r"\{[^{}]*\"tool\"\s*:\s*\"([a-zA-Z0-9_]+)\"[^{}]*\}", text):
            try:
                parsed = json.loads(match.group(0))
                tool = parsed.get("tool")
                params = parsed.get("parameters") or parsed.get("arguments") or {}
                calls.append((tool, params))
            except Exception:
                pass

        return calls

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
        return [
            {"role": m["role"], "content": m["text"]}
            for m in convs[-10:]
            if m.get("role") in ("user", "assistant")
        ]


# Singleton
orchestrator = Orchestrator()
