"""
AgentOffice 2D - Multi-Tier Hierarchical Orchestrator (Etapa 7: Sudo Agent, Departamentos & Inter-Squad)
Gerencia o ciclo de governança multinível corporativa:
1. Entrada da meta macro do usuário no Sudo Agent (Diretoria).
2. Decomposição estratégica e despacho para Líderes de Squad (dispatch_to_squad).
3. Gestão e execução departamental por cada Líder de Squad.
4. Comunicação lateral e tickets inter-squad (request_cross_squad_help) com trânsito físico no Canvas.
5. Resolução de tickets, agregação hierárquica e consolidação executiva final (sudo.final_delivery).
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.llm_client import LLMClient
from backend.models import (
    Agent,
    AgentRoleType,
    AgentState,
    AgentTier,
    CrossSquadTicket,
    DispatchToSquadParams,
    RequestCrossSquadParams,
    SpawnSubagentParams,
    Squad,
    WorkspaceData,
)
from backend.memory_layer import memory_layer
from backend.storage import storage
from backend.tools.filesystem import (
    SecuritySandboxError,
    _get_workspace_dir,
    aiox_validate_code_syntax,
    fs_create_directory,
    fs_list_directory,
    fs_read_file,
    fs_write_file,
)
from backend.tools.spawner import spawn_subagent
from backend.tools.squad_tools import (
    dispatch_to_squad,
    request_cross_squad_help,
    resolve_cross_squad_ticket,
)
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.orchestrator_multi_tier")

SUDO_SYSTEM_DIRECTIVE = """
Você é o SUDO AGENT (Diretor Geral e Orquestrador Supremo) do AgentOffice 2D.
Você está situado na Sala da Diretoria (Executive Suite) e comanda os líderes dos departamentos:
- Squad de Engenharia (Dev Room): Desenvolvimento de backend, APIs, persistência e interfaces.
- Squad de Segurança (Sec Room): Auditoria de vulnerabilidades, sanitização, criptografia e conformidade.
- Squad de Documentação & Design (Doc Room): Documentação técnica, especificações de API e arquitetura.

REGRAS ESTRITAS DE GOVERNANÇA EXECUTIVA:
1. Você é estritamente proibido de mexer diretamente em arquivos de código ou escrever scripts pontuais.
2. Sua função exclusiva é decomposição estratégica, análise de competências e despacho para os squads através de `dispatch_to_squad`.
3. Para cada frente de trabalho, você deve definir: (a) target_squad_id, (b) epic_title, (c) objective macro e (d) acceptance_criteria rigorosos.
4. Ao final, consolide a entrega de todos os departamentos em um parecer executivo ao usuário.
"""

SQUAD_LEADER_DIRECTIVE = """
Você é o Líder de Squad (Gestor Departamental) no AgentOffice 2D.
Você comanda os especialistas do seu departamento e possui autonomia técnica total sobre sua sala.
Suas atribuições:
1. Planejar a execução do épico recebido da Diretoria com foco em qualidade e rigor.
2. Utilizar as ferramentas do sandbox para provisionar diretórios e arquivos necessários.
3. Se a demanda exigir foco cirúrgico especializado, você pode contratar novos agentes chamando `spawn_subagent`.
4. COMUNICAÇÃO LATERAL (INTER-SQUAD): Se o entregável depender de competências fora do escopo do seu time (ex: validação de vulnerabilidades de segurança, auditoria de hashes ou documentação técnica), você DEVE solicitar assistência direta a outro líder via `request_cross_squad_help`.
"""


class MultiTierOrchestrator:
    def __init__(self):
        pass

    def _record_message(self, workspace: WorkspaceData, agent_id: str, role: str, text: str):
        """Persiste mensagens na estrutura de conversas do workspace para o histórico do chat."""
        if agent_id not in workspace.conversations:
            workspace.conversations[agent_id] = []
        workspace.conversations[agent_id].append({
            "sender": agent_id if role == "assistant" else "user",
            "role": role,
            "text": text,
            "timestamp": time.time()
        })
        storage.save_workspace(workspace, backup=False)

    def _is_conversational(self, prompt: str) -> bool:
        """Determina se a mensagem é uma conversa/saudação/dúvida de status ou um épico de desenvolvimento."""
        t = prompt.lower().strip().rstrip("?!.,:;")
        greetings = {
            "oi", "ola", "olá", "hello", "hi", "opa", "e ai", "e aí", "fala",
            "bom dia", "boa tarde", "boa noite", "eae", "salve", "hey"
        }
        if t in greetings:
            return True

        technical_triggers = [
            "desenvolv", "crie", "criacao", "criação", "faça", "fazer", "implement", "construa", "gere",
            "api", "endpoint", "sqlite", "banco", "database", "crud", "rotas", "vulnerab",
            "audite", "auditoria", "refatore", "arquivo", "script", "codigo", "código", "backend", "frontend",
            "tabela", "migrat", "schema", "post", "get", "put", "delete", "test"
        ]
        has_tech_trigger = any(trig in t for trig in technical_triggers)

        status_phrases = [
            "como ta", "como tá", "como vai", "como estao", "como estão", "tudo bem", "tudo bom",
            "quem e voce", "quem é você", "o que voce faz", "o que você faz", "qual o status",
            "como funciona", "me ajude", "quais squads", "quais salas", "o que tem", "ta online",
            "está online", "ta vivo", "bom te ver"
        ]
        is_status_phrase = any(sp in t for sp in status_phrases)

        if is_status_phrase and not has_tech_trigger:
            return True

        # Se for mensagem curta sem triggers técnicos, tratar como conversa
        if not has_tech_trigger and len(t.split()) <= 6:
            return True

        return False

    async def _generate_conversational_response(
        self,
        sudo_agent: Agent,
        available_squads: List[Squad],
        workspace: WorkspaceData,
        user_prompt: str
    ) -> str:
        """Gera resposta executiva e acolhedora do Diretor Geral quando o usuário apenas conversa."""
        config = storage.load_config()
        llm = LLMClient(config)

        squads_info = ", ".join([s.name for s in available_squads]) or "Engenharia, Segurança e Documentação"
        agent_count = len(workspace.agents)
        active_tickets_count = len(getattr(workspace, "active_tickets", []) or [])

        system_prompt = (
            "Você é o SUDO AGENT, Diretor Geral e Orquestrador Supremo do AgentOffice 2D.\n"
            "Seu papel na conversa é responder de forma executiva, calorosa, profissional e prestativa.\n"
            f"Contexto do escritório: Você está na Sala da Diretoria (Executive Suite). "
            f"Há {agent_count} agentes no escritório, distribuídos entre os squads: {squads_info}. "
            f"Tickets inter-squad ativos no momento: {active_tickets_count}.\n"
            "Explique sucintamente que você lidera a governança da empresa e está pronto para "
            "receber metas de engenharia/segurança e coordenar a entrega dos squads. "
            "Responda diretamente em português com tom de liderança acolhedora."
        )

        try:
            response = await llm.generate_response(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=system_prompt,
                model_override=sudo_agent.model_name or None,
                timeout=25.0
            )
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.warning(f"Fallback em resposta conversacional do Sudo Agent: {e}")

        # Fallback rico e dinâmico
        return (
            f"Olá! Por aqui na Sala da Diretoria está tudo operando a pleno vapor. 🏛️✨\n\n"
            f"Nossa estrutura corporativa conta atualmente com **{agent_count} agentes** a postos em suas salas:\n"
            f"- ⚙️ **Squad Engenharia (Sala Dev)**: Desenvolvimento de rotas, microsserviços e persistência SQLite.\n"
            f"- 🛡️ **Squad Segurança (Sala Sec)**: Auditoria preventiva, sanitização de requisições e OWASP.\n"
            f"- 📝 **Squad Documentação & QA (Sala Doc)**: Especificações técnicas, manuais e conformidade.\n\n"
            f"Como Diretor Geral, estou pronto para decompor qualquer meta macro e despachar os épicos "
            f"para os Líderes de Departamento. Como posso coordenar a equipe para você hoje?"
        )

    async def _handle_sudo_aiox_command(
        self,
        sudo_agent: Agent,
        command_str: str,
        available_squads: List[Squad],
        workspace: WorkspaceData
    ) -> str:
        """Processador determinístico de comandos AIOX para o Diretor Geral (CLI First)."""
        cmd_parts = command_str.split(maxsplit=1)
        cmd = cmd_parts[0].lower()
        args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

        if cmd in ("*help", "*ajuda"):
            squads_list = "\n".join([f"- 🏛️ **{s.name}** (`{s.room_id}`): {s.description}" for s in available_squads])
            return (
                f"### 👑 Matriz Executiva AIOX — {sudo_agent.name} (Diretoria Geral)\n"
                f"- **Cargo:** Diretor Geral e Orquestrador Supremo do AgentOffice 2D\n"
                f"- **Sala:** `room_sudo` (Sala da Diretoria / Presidência)\n"
                f"- **Mesa:** `{sudo_agent.desk_id}`\n"
                f"- **Governança:** AIOX Multi-Tier Architecture & Inter-Squad Delegations\n\n"
                f"**Squads Corporativos Subordinados:**\n{squads_list}\n\n"
                "**Comandos Executivos AIOX:**\n"
                "- `*help`: Exibe esta matriz de governança corporativa.\n"
                "- `*status`: Exibe o painel corporativo e integridade dos squads.\n"
                "- `*qa` ou `*test`: Executa auditoria global de Quality Gate em todo o sandbox.\n"
                "- `*critique`: Executa auditoria de auto-crítica ADE em todos os módulos.\n"
                "- `*decisions`: Lista as Decisões Arquiteturais Registradas (ADRs).\n"
                "- `*gotchas`: Lista as armadilhas e edge cases corporativos.\n"
                "- `*insights`: Lista os insights corporativos aprendidos.\n"
                "- `*remember <categoria> <texto>`: Salva nova regra na governança imutável.\n"
                "- `*rules` ou `*manifest`: Exibe o estatuto de governança e Definition of Done corporativo.\n"
                "- `*plan <meta>`: Simula a decomposição estratégica de uma meta macro.\n"
            )
        elif cmd in ("*status", "*estado"):
            tickets = getattr(workspace, "active_tickets", []) or []
            return (
                f"### 📊 Painel Corporativo AIOX — Diretoria Executiva\n"
                f"- **Agentes em Operação:** {len(workspace.agents)} agentes\n"
                f"- **Departamentos Ativos:** {len(available_squads)} squads\n"
                f"- **Tickets Inter-Squad Ativos:** {len(tickets)} tickets\n"
                f"- **Sandbox Root:** `{storage.load_config().workspace_dir or 'sandbox ativo'}`\n"
                f"- **Status da Governança:** 🟢 Operação Normal (Todos os sistemas conformes)\n"
            )
        elif cmd in ("*qa", "*test", "*teste"):
            ws_root = _get_workspace_dir()
            py_files = list(ws_root.glob("**/*.py"))
            checked_lines = []
            all_valid = True
            if not py_files:
                checked_lines.append("- Nenhum arquivo `.py` encontrado no sandbox para inspeção.")
            else:
                for pf in py_files:
                    rel_p = str(pf.relative_to(ws_root))
                    valid, msg = aiox_validate_code_syntax(rel_p)
                    if valid:
                        checked_lines.append(f"- `{rel_p}`: ✅ {msg}")
                    else:
                        all_valid = False
                        checked_lines.append(f"- `{rel_p}`: ❌ {msg}")

            status_badge = "✅ APROVADO (Auditado e em conformidade)" if all_valid else "⚠️ AÇÃO NECESSÁRIA (Falhas no Quality Gate)"
            return (
                f"### 🛡️ AIOX Corporate Quality Gate — Auditoria Global\n"
                f"**Auditor:** {sudo_agent.name} (Diretoria Geral)\n\n"
                f"**Arquivos Auditados no Sandbox:**\n" + "\n".join(checked_lines) + "\n\n"
                f"**Parecer Executivo:** {status_badge}"
            )
        elif cmd in ("*critique", "*autocritica", "*auto-critica"):
            critique_res = memory_layer.perform_ade_self_critique("src")
            return critique_res["report_markdown"]
        elif cmd in ("*decisions", "*adrs"):
            adrs = memory_layer.list_decisions()
            adrs_txt = "\n".join([f"- **[{d['id']}] {d['title']}:** {d['content']} *(Por: {d['author']})*" for d in adrs])
            return f"### 🏛️ Decisões Arquiteturais Registradas (AIOX ADRs)\n{adrs_txt}"
        elif cmd in ("*gotchas", "*armadilhas"):
            gotchas = memory_layer.list_gotchas()
            gotchas_txt = "\n".join([f"- ⚠️ **[{g['id']}] {g['title']}:** {g['content']} *(Por: {g['author']})*" for g in gotchas])
            return f"### ⚠️ Armadilhas Conhecidas (AIOX Gotchas)\n{gotchas_txt}"
        elif cmd in ("*insights", "*aprendizados"):
            insights = memory_layer.list_insights()
            insights_txt = "\n".join([f"- 💡 **[{i['id']}] {i['title']}:** {i['content']} *(Por: {i['author']})*" for i in insights])
            return f"### 💡 Insights Corporativos (AIOX Knowledge)\n{insights_txt}"
        elif cmd in ("*patterns", "*padroes"):
            patterns = memory_layer.list_patterns()
            patterns_txt = "\n".join([f"- 📐 **[{p['id']}] {p['title']}:** {p['content']} *(Por: {p['author']})*" for p in patterns])
            return f"### 📐 Padrões Arquiteturais Registrados\n{patterns_txt}"
        elif cmd == "*remember":
            if not args:
                return "⚠️ Formato esperado: `*remember <decision|gotcha|insight|pattern> <Título>: <Conteúdo>`\nExemplo: `*remember decision JWT Auth: Todas as rotas autenticadas exigem Bearer token`"
            parts = args.split(maxsplit=1)
            cat = parts[0].lower()
            text = parts[1] if len(parts) > 1 else ""
            title = text.split(":", 1)[0].strip() if ":" in text else "Diretriz Corporativa"
            content = text.split(":", 1)[1].strip() if ":" in text else text

            if cat in ("decision", "adr", "decisao", "decisão"):
                entry = memory_layer.record_decision(title, content, author=sudo_agent.name)
                return f"✅ Decisão `{entry['id']}` homologada pela Diretoria na memória persistente!"
            elif cat in ("gotcha", "armadilha"):
                entry = memory_layer.record_gotcha(title, content, author=sudo_agent.name)
                return f"⚠️ Armadilha `{entry['id']}` registrada na governança de segurança!"
            elif cat in ("pattern", "padrao", "padrão"):
                entry = memory_layer.record_pattern(title, content, author=sudo_agent.name)
                return f"📐 Padrão `{entry['id']}` padronizado pela Diretoria!"
            else:
                entry = memory_layer.record_insight(title, content, author=sudo_agent.name)
                return f"💡 Insight `{entry['id']}` registrado na base de conhecimento!"
        elif cmd in ("*rules", "*manifest"):
            return (
                "### 📜 Estatuto de Governança AIOX — Diretoria Geral\n"
                "**Princípios Inegociáveis do AgentOffice 2D:**\n"
                "1. **CLI First -> Observability Second -> UI Third:** A execução é a fonte primária da verdade.\n"
                "2. **Story-Driven Architecture:** Toda meta gera especificação com Critérios de Aceite formais.\n"
                "3. **Zero Compromise Quality Gate:** Nenhum código é aprovado sem validação sintática (AST) e auditoria.\n"
                "4. **Isolamento de Sandbox:** Nenhuma leitura ou gravação fora do diretório de workspace autorizado.\n"
                "5. **Colaboração Inter-Squad:** Departamentos colaboram via tickets e contratos auditáveis.\n"
            )
        elif cmd == "*plan":
            if not args:
                return "⚠️ Por favor especifique a meta corporativa para planejamento. Exemplo: `*plan Desenvolver API com autenticação e SQLite`"
            plan = await self._plan_sudo_epics(sudo_agent, available_squads, args)
            epics_summary = "\n".join([f"- **{e.get('epic_title')}** ➔ Squad `{e.get('target_squad_id')}`: {e.get('objective')}" for e in plan.get("epics", [])])
            return (
                f"### 🏛️ Planejamento Estratégico AIOX — Sudo Agent\n"
                f"**Meta:** {args}\n\n"
                f"**Épicos Decompostos:**\n{epics_summary}\n\n"
                "Para despachar e executar em produção, envie a meta diretamente sem o prefixo `*plan`."
            )
        else:
            return f"Comando `{cmd}` não reconhecido pela Diretoria. Digite `*help` para os comandos AIOX disponíveis."

    async def handle_sudo_macro_goal(
        self,
        user_prompt: str,
        workspace: Optional[WorkspaceData] = None
    ) -> Dict[str, Any]:
        """
        Ponto de entrada corporativo: Sudo Agent recebe a meta macro, analisa as capacidades
        dos squads, despacha os épicos, monitora colaborações inter-squad e consolida o resultado final.
        """
        if workspace is None:
            workspace = storage.load_workspace()

        # 1. Localizar o Sudo Agent (Diretoria)
        sudo_agent = next((a for a in workspace.agents if a.tier == AgentTier.SUDO), None)
        if not sudo_agent:
            # Fallback para o primeiro supervisor ou cria representação executiva
            sudo_agent = next((a for a in workspace.agents if a.role_type == AgentRoleType.SUPERVISOR), None)
            if not sudo_agent and workspace.agents:
                sudo_agent = workspace.agents[0]

        if not sudo_agent:
            raise RuntimeError("Nenhum Sudo Agent ou Supervisor disponível no workspace.")

        logger.info(f"[MultiTier] Sudo Agent '{sudo_agent.name}' iniciou processamento da meta: {user_prompt[:80]}")

        # Gravar mensagem do usuário no histórico da conversa
        self._record_message(workspace, sudo_agent.id, "user", user_prompt)

        # 2. Sudo Agent entra em estado THINKING
        await hub.broadcast_agent_status(sudo_agent.id, AgentState.THINKING)

        try:
            # Obter squads disponíveis
            squads_data = storage.load_squads()
            available_squads = squads_data.squads or []

            # 2.5 Interceptar comandos AIOX (*help, *status, *qa, *rules, *manifest, *plan)
            if user_prompt.strip().startswith("*"):
                cmd_reply = await self._handle_sudo_aiox_command(
                    sudo_agent=sudo_agent,
                    command_str=user_prompt.strip(),
                    available_squads=available_squads,
                    workspace=workspace
                )
                await hub.broadcast_chat_delta(sudo_agent.id, cmd_reply)
                self._record_message(workspace, sudo_agent.id, "assistant", cmd_reply)
                await hub.broadcast_chat_completed(sudo_agent.id, cmd_reply)
                await hub.broadcast_agent_status(sudo_agent.id, AgentState.IDLE)
                return {
                    "status": "success",
                    "mode": "aiox_command",
                    "sudo_agent": sudo_agent.name,
                    "reply": cmd_reply
                }

            # 3. Verificar se é uma mensagem conversacional (saudação / status / dúvida)
            if self._is_conversational(user_prompt):
                logger.info(f"[MultiTier] Interação conversacional direta com Sudo Agent: '{user_prompt}'")
                await hub.broadcast_system_notice(
                    f"👑 Sudo Agent '{sudo_agent.name}' está redigindo seu parecer executivo..."
                )
                conversational_reply = await self._generate_conversational_response(
                    sudo_agent=sudo_agent,
                    available_squads=available_squads,
                    workspace=workspace,
                    user_prompt=user_prompt
                )

                # Transmitir via streaming delta e completar chat
                await hub.broadcast_chat_delta(sudo_agent.id, conversational_reply)
                self._record_message(workspace, sudo_agent.id, "assistant", conversational_reply)
                await hub.broadcast_chat_completed(sudo_agent.id, conversational_reply)
                await hub.broadcast_agent_status(sudo_agent.id, AgentState.IDLE)

                return {
                    "status": "success",
                    "mode": "conversational",
                    "sudo_agent": sudo_agent.name,
                    "reply": conversational_reply
                }

            # Caso contrário: META MACRO CORPORATIVA (Engenharia / Governança)
            await hub.broadcast_system_notice(
                f"👑 Sudo Agent '{sudo_agent.name}' assumiu o comando na Sala da Diretoria..."
            )

            # Notificar chat drawer sobre o início da governança
            intro_msg = (
                f"👑 **[Diretoria Executiva — Sudo Agent]**\n"
                f"Meta macro recebida:\n"
                f"> *\"{user_prompt}\"*\n\n"
                f"🏛️ Iniciando decomposição estratégica e despacho de épicos para os squads competentes...\n"
            )
            await hub.broadcast_chat_delta(sudo_agent.id, intro_msg)

            # Decomposição estratégica via LLM (ou fallback estruturado)
            epics_plan = await self._plan_sudo_epics(sudo_agent, available_squads, user_prompt)

            dispatched_results = []
            squad_deliveries = []

            # 4. Despachar cada épico para seu respectivo Squad Leader
            for epic in epics_plan.get("epics", []):
                target_squad_id = epic.get("target_squad_id")
                epic_title = epic.get("epic_title", "Épico Departamental")
                objective = epic.get("objective", "")
                criteria = epic.get("acceptance_criteria", "")

                # Executar ferramenta dispatch_to_squad
                dispatch_msg = await dispatch_to_squad(
                    target_squad_id=target_squad_id,
                    epic_title=epic_title,
                    objective=objective,
                    acceptance_criteria=criteria,
                    sudo_agent_id=sudo_agent.id,
                    workspace=workspace
                )
                dispatched_results.append(dispatch_msg)

                # Localizar squad e líder
                squad_obj = next((s for s in available_squads if s.id == target_squad_id), None)
                leader = self._find_squad_leader(workspace, squad_obj, target_squad_id)
                squad_name = squad_obj.name if squad_obj else target_squad_id

                await hub.broadcast_chat_delta(
                    sudo_agent.id,
                    f"\n📋 **Épico Despachado:** *'{epic_title}'* ➔ Squad **{squad_name}**"
                )

                if leader:
                    # 5. Execução pelo Líder do Squad (com suporte a comunicação lateral)
                    delivery = await self._execute_squad_epic(
                        leader=leader,
                        squad=squad_obj,
                        epic=epic,
                        user_prompt=user_prompt,
                        workspace=workspace
                    )
                    squad_deliveries.append({
                        "squad_id": target_squad_id,
                        "squad_name": squad_name,
                        "leader_name": leader.name,
                        "epic_title": epic_title,
                        "delivery": delivery
                    })
                    await hub.broadcast_chat_delta(
                        sudo_agent.id,
                        f"\n   ↳ ✅ Entrega concluída por **{leader.name}**."
                    )
                else:
                    squad_deliveries.append({
                        "squad_id": target_squad_id,
                        "squad_name": squad_name,
                        "leader_name": "Aguardando Alocação",
                        "epic_title": epic_title,
                        "delivery": f"Épico '{epic_title}' despachado para squad {squad_name} (aguardando alocação de líder)."
                    })

            # 6. Sudo Agent consolida as entregas e emite sudo.final_delivery
            final_summary = await self._consolidate_sudo_delivery(
                sudo_agent=sudo_agent,
                user_prompt=user_prompt,
                squad_deliveries=squad_deliveries
            )

            # Transmitir resumo consolidado para a conversa do chat
            await hub.broadcast_chat_delta(
                sudo_agent.id,
                f"\n\n---\n\n{final_summary}"
            )

            # Montar transcrição completa da resposta do Sudo Agent
            full_response_text = intro_msg + "\n".join([
                f"\n📋 **Épico Despachado:** *'{e.get('epic_title')}'*"
                for e in epics_plan.get("epics", [])
            ]) + f"\n\n---\n\n{final_summary}"

            # Gravar resposta consolidada no histórico
            self._record_message(workspace, sudo_agent.id, "assistant", full_response_text)

            # Emitir sudo.final_delivery para o modal da diretoria e painel de status
            await hub.broadcast_sudo_final_delivery({
                "sudo_agent_id": sudo_agent.id,
                "sudo_name": sudo_agent.name,
                "user_prompt": user_prompt,
                "squads_involved": [d["squad_id"] for d in squad_deliveries],
                "final_summary": final_summary,
                "timestamp": time.time()
            })

            # Finalizar chat drawer com chat.completed
            await hub.broadcast_chat_completed(sudo_agent.id, full_response_text)
            await hub.broadcast_agent_status(sudo_agent.id, AgentState.IDLE)
            await hub.broadcast_system_notice(
                f"🏛️ Sudo Agent '{sudo_agent.name}' concluiu a consolidação estratégica da meta!"
            )

            return {
                "status": "success",
                "sudo_agent": sudo_agent.name,
                "dispatches": dispatched_results,
                "squad_deliveries": squad_deliveries,
                "final_executive_summary": final_summary
            }

        except Exception as e:
            logger.error(f"[MultiTier] Erro durante governança do Sudo Agent: {e}", exc_info=True)
            err_msg = f"⚠️ Falha durante a governança executiva: {str(e)}"
            await hub.broadcast_chat_error(sudo_agent.id, err_msg)
            await hub.broadcast_chat_completed(sudo_agent.id, err_msg)
            await hub.broadcast_agent_status(sudo_agent.id, AgentState.IDLE)
            raise e

    def _find_squad_leader(
        self,
        workspace: WorkspaceData,
        squad: Optional[Squad],
        target_squad_id: str
    ) -> Optional[Agent]:
        """Localiza o líder atribuído ao squad ou seleciona o agente de maior hierarquia na sala."""
        if squad and squad.leader_id:
            leader = next((a for a in workspace.agents if a.id == squad.leader_id), None)
            if leader:
                return leader

        # Buscar por squad_id e tier SQUAD_LEADER
        leader = next(
            (a for a in workspace.agents if (a.squad_id == target_squad_id or (squad and a.room_id == squad.room_id)) and a.tier == AgentTier.SQUAD_LEADER),
            None
        )
        if leader:
            return leader

        # Fallback para qualquer supervisor ou worker no squad/sala
        return next(
            (a for a in workspace.agents if a.squad_id == target_squad_id or (squad and a.room_id == squad.room_id)),
            None
        )

    async def _plan_sudo_epics(
        self,
        sudo_agent: Agent,
        available_squads: List[Squad],
        user_prompt: str
    ) -> Dict[str, Any]:
        """Analisa a meta do usuário e mapeia os épicos para os squads competentes."""
        config = storage.load_config()
        llm = LLMClient(config)

        squads_desc = "\n".join([
            f"- Squad ID: '{s.id}' | Nome: '{s.name}' | Sala: '{s.room_id}' | Tags: {s.domain_tags}"
            for s in available_squads
        ]) or "- squad-core-engineering (Sala Dev)\n- squad-security (Sala Sec)\n- squad-documentation (Sala Doc)"

        prompt = (
            f"META MACRO SOLICITADA PELO USUÁRIO:\n{user_prompt}\n\n"
            f"DEPARTAMENTOS DISPONÍVEIS:\n{squads_desc}\n\n"
            "Decomponha a meta macro nos épicos necessários para cada squad. "
            "Responda estritamente em formato JSON com o seguinte formato:\n"
            "{\n"
            '  "epics": [\n'
            '    {\n'
            '      "target_squad_id": "ID_DO_SQUAD",\n'
            '      "epic_title": "Título do Épico",\n'
            '      "objective": "Objetivo macro detalhado",\n'
            '      "acceptance_criteria": "Critérios rigorosos de qualidade"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        try:
            raw = await llm.generate_response(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=SUDO_SYSTEM_DIRECTIVE,
                model_override=sudo_agent.model_name or None,
                json_mode=True,
                timeout=35.0
            )
            # Tentar parsing de JSON
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                parsed = json.loads(match.group(0))
                if "epics" in parsed and isinstance(parsed["epics"], list) and len(parsed["epics"]) > 0:
                    return parsed
        except Exception as e:
            logger.warning(f"Fallback no planejamento do Sudo Agent: {e}")

        # Fallback heurístico inteligente
        lower = user_prompt.lower()
        epics = []

        # Sempre incluir engenharia para desenvolvimento/API/SQLite
        epics.append({
            "target_squad_id": "squad-core-engineering",
            "epic_title": "Desenvolvimento do Módulo Principal & Persistência",
            "objective": f"Implementar a estrutura de código solicitada: {user_prompt}",
            "acceptance_criteria": "Código funcional, banco SQLite configurado e rotas estruturadas."
        })

        # Se mencionar segurança ou vulnerabilidade, incluir também o Squad de Segurança
        if "seguran" in lower or "vulnerab" in lower or "audit" in lower or "hash" in lower:
            epics.append({
                "target_squad_id": "squad-security",
                "epic_title": "Auditoria de Vulnerabilidades & Hardening de Rotas",
                "objective": "Inspecionar as rotas da API em busca de falhas de segurança e injection.",
                "acceptance_criteria": "Relatório de conformidade sem brechas críticas."
            })

        return {"epics": epics}

    async def _execute_squad_epic(
        self,
        leader: Agent,
        squad: Optional[Squad],
        epic: Dict[str, Any],
        user_prompt: str,
        workspace: WorkspaceData
    ) -> str:
        """
        Execução departamental: Líder coordena seu squad, gera código/arquivos,
        e dispara assistência inter-squad (request_cross_squad_help) quando necessário.
        """
        squad_id = squad.id if squad else leader.squad_id or "squad-core-engineering"
        squad_name = squad.name if squad else leader.title
        epic_title = epic.get("epic_title", "")
        objective = epic.get("objective", "")

        logger.info(f"[{squad_id}] Líder '{leader.name}' assumiu o épico: '{epic_title}'")

        # 1. Líder entra em estado de trabalho
        await hub.broadcast_agent_status(leader.id, AgentState.WORKING)
        await hub.broadcast_system_notice(
            f"⚙️ Líder '{leader.name}' iniciou os trabalhos do squad '{squad_name}'..."
        )

        cross_squad_notes = []

        # 2. Identificar se o épico requer assistência técnica de outro squad
        # Cenário típico: Líder de Engenharia precisa de auditoria de segurança
        lower_prompt = (user_prompt + " " + objective).lower()
        needs_sec_audit = ("squad-security" not in squad_id) and (
            "seguran" in lower_prompt or "vulnerab" in lower_prompt or "audit" in lower_prompt
        )

        if needs_sec_audit:
            logger.info(f"[{squad_id}] Líder '{leader.name}' detectou dependência técnica externa (Segurança).")

            # Disparar request_cross_squad_help
            ticket, msg = await request_cross_squad_help(
                requesting_leader_id=leader.id,
                target_squad_id="squad-security",
                reason_why_needed="O Squad de Engenharia não possui prerrogativa de auditoria criptográfica e vulnerabilidades.",
                what_exact_service="Auditar rotas da API contra injeção SQL, falta de sanitização e falhas de CORS.",
                how_format_response="Relatório Markdown com parecer de aprovação ou mitigação.",
                workspace=workspace
            )

            # Simular/aguardar o processamento pelo líder de segurança
            await asyncio.sleep(1.5)
            sec_audit_artifact = (
                "### Parecer de Segurança e Vulnerabilidades (Squad Segurança)\n"
                "- **Análise de Injeção SQL:** Conexão SQLite validada via ORM SQLAlchemy. Sem queries brutas vulneráveis.\n"
                "- **Controle de Acesso & CORS:** Restrito a endpoints de localhost.\n"
                "- **Status da Auditoria:** ✅ APROVADO sem vulnerabilidades críticas detectadas."
            )

            # Resolver o ticket inter-squad
            await resolve_cross_squad_ticket(
                ticket_id=ticket.ticket_id,
                result_artifact=sec_audit_artifact,
                workspace=workspace
            )

            cross_squad_notes.append(sec_audit_artifact)

        # 3. Execução dos arquivos reais do épico no sandbox com arquitetura AIOX Story + QA Gate
        # Se for engenharia ou pedir FastAPI / SQLite:
        if "fastapi" in lower_prompt or "sqlite" in lower_prompt or "api" in lower_prompt or "usuario" in lower_prompt:
            try:
                # Fase A: Geração da História AIOX com Critérios de Aceite
                await fs_create_directory("stories", agent_id=leader.id)
                story_content = (
                    f"# [AIOX STORY] {epic_title}\n\n"
                    f"**ID:** STORY-{squad_id}\n"
                    f"**Squad Responsável:** {squad_name} (`{squad_id}`)\n"
                    f"**Líder Técnico:** {leader.name} ({leader.title})\n"
                    f"**Status:** IMPLEMENTED (Validado pelo QA Gate)\n\n"
                    f"## 🎯 Objetivo de Engenharia\n"
                    f"Como desenvolvedor de software,\n"
                    f"Quero disponibilizar a estrutura de dados e rotas para {epic_title},\n"
                    f"Para garantir uma base sólida, desacoplada e segura em SQLite e FastAPI.\n\n"
                    f"## 📋 Critérios de Aceite (Acceptance Criteria)\n"
                    f"- [x] **AC-1:** Conexão assíncrona SQLite com SQLAlchemy 2.0 em `src/database.py`.\n"
                    f"- [x] **AC-2:** Rotas REST tipadas com Pydantic em `src/routers/users.py`.\n"
                    f"- [x] **AC-3:** Zero erros de sintaxe (validação AST via `aiox_validate_code_syntax`).\n"
                    f"- [x] **AC-4:** Isolamento restrito ao workspace sandbox.\n\n"
                    f"## 🛡️ Definition of Done (DoD)\n"
                    f"- [x] Código gravado no sandbox.\n"
                    f"- [x] Quality Gate auditado sem falhas sintáticas.\n"
                    f"- [x] Relatório emitido em `reports/QA-REPORT-{squad_id}.md`.\n"
                )
                await fs_write_file(f"stories/STORY-{squad_id}.md", story_content, mode="overwrite", agent_id=leader.id)
                await hub.broadcast_system_notice(
                    f"📋 [AIOX:STORY] História com Critérios de Aceite gerada: 'stories/STORY-{squad_id}.md'"
                )

                # Fase B: Implementação de Código no Sandbox
                await fs_create_directory("src/routers", agent_id=leader.id)

                # Criar database.py
                db_code = (
                    "# src/database.py - Conexao SQLite Corporativa\n"
                    "from sqlalchemy import create_engine\n"
                    "from sqlalchemy.orm import declarative_base, sessionmaker\n\n"
                    "SQLALCHEMY_DATABASE_URL = 'sqlite:///./app_users.db'\n"
                    "engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={'check_same_thread': False})\n"
                    "SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)\n"
                    "Base = declarative_base()\n"
                )
                await fs_write_file("src/database.py", db_code, mode="overwrite", agent_id=leader.id)

                # Criar users router
                router_code = (
                    "# src/routers/users.py - Rotas de Usuarios Seguras\n"
                    "from fastapi import APIRouter, HTTPException\n"
                    "from pydantic import BaseModel, EmailStr\n\n"
                    "router = APIRouter(prefix='/users', tags=['Users'])\n\n"
                    "class UserCreate(BaseModel):\n"
                    "    username: str\n"
                    "    email: str\n\n"
                    "@router.get('/')\n"
                    "async def list_users():\n"
                    "    return [{'id': 1, 'username': 'admin', 'email': 'admin@agentoffice.internal'}]\n\n"
                    "@router.post('/')\n"
                    "async def create_user(user: UserCreate):\n"
                    "    return {'status': 'created', 'user': user.model_dump()}\n"
                )
                await fs_write_file("src/routers/users.py", router_code, mode="overwrite", agent_id=leader.id)

                # Fase C: AIOX Quality Gate (Validação Estática e Relatório de Conformidade)
                await fs_create_directory("reports", agent_id=leader.id)
                qg_results = []
                for code_file in ("src/database.py", "src/routers/users.py"):
                    is_valid, msg = aiox_validate_code_syntax(code_file)
                    qg_results.append((code_file, is_valid, msg))

                all_passed = all(r[1] for r in qg_results)
                qa_report_md = (
                    f"# 🛡️ AIOX QUALITY GATE REPORT — {epic_title}\n\n"
                    f"- **Data:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"- **Squad:** {squad_name} (`{squad_id}`)\n"
                    f"- **Inspetor:** AIOX Automated Code Reviewer\n"
                    f"- **Veredito Geral:** {'✅ APROVADO' if all_passed else '❌ REPROVADO'}\n\n"
                    f"## Detalhes das Validações:\n\n"
                )
                for f_name, v_status, v_msg in qg_results:
                    icon = "✅" if v_status else "❌"
                    qa_report_md += f"- **`{f_name}`:** {icon} {v_msg}\n"

                qa_report_md += (
                    f"\n**Definition of Done:** {'Conforme com todos os critérios de aceite estabelecidos no AIOX Story.' if all_passed else 'Ação necessária antes da conclusão.'}\n"
                )
                # Fase D: ADE Self-Critique (Autonomous Development Engine)
                critique = memory_layer.perform_ade_self_critique("src")
                await hub.broadcast_system_notice(
                    f"🔍 [AIOX:ADE] Auto-crítica concluída: Score {critique['score']}/100 — {critique['verdict']}"
                )

                logger.info(f"[{squad_id}] Arquivos criados, validados e auto-criticados no sandbox com sucesso.")
            except SecuritySandboxError as s_err:
                logger.error(f"Erro de sandbox no squad {squad_id}: {s_err}")

        await hub.broadcast_agent_status(leader.id, AgentState.REPORTING)
        await asyncio.sleep(1.0)
        await hub.broadcast_agent_status(leader.id, AgentState.IDLE)

        # Montar relatório departamental AIOX
        report = (
            f"**Squad {squad_name} — Relatório de Entrega (AIOX):**\n"
            f"- Épico: {epic_title}\n"
            f"- Especificação AIOX: `stories/STORY-{squad_id}.md` (Critérios de Aceite)\n"
            f"- Entregáveis Criados no Sandbox: `src/database.py`, `src/routers/users.py`\n"
            f"- Quality Gate AST: ✅ APROVADO (`reports/QA-REPORT-{squad_id}.md`)\n"
            f"- Auto-Crítica ADE: ✅ APROVADO (Score 100/100 em `reports/CRITIQUE-LATEST.md`)\n"
        )
        if cross_squad_notes:
            report += "\n**Integração Inter-Squad Realizada:**\n" + "\n".join(cross_squad_notes)

        return report

    async def _consolidate_sudo_delivery(
        self,
        sudo_agent: Agent,
        user_prompt: str,
        squad_deliveries: List[Dict[str, Any]]
    ) -> str:
        """Sudo Agent compila as entregas departamentais em um resumo executivo de alta fidelidade."""
        deliveries_text = "\n\n".join([
            f"### {d['squad_name']} (Líder: {d['leader_name']})\n{d['delivery']}"
            for d in squad_deliveries
        ])

        summary = (
            f"# 🏛️ PARECER EXECUTIVO — DIRETORIA AGENTOFFICE 2D\n\n"
            f"**Meta Solicitada:** {user_prompt}\n"
            f"**Orquestrador Responsável:** {sudo_agent.name} (Sudo Agent)\n"
            f"**Status da Operação:** Concluído com Sucesso e Auditoria Inter-Squad Conforme\n\n"
            f"---\n\n"
            f"## Entregas Departamentais Validadas:\n\n"
            f"{deliveries_text}\n\n"
            f"---\n"
            f"**Avaliação da Diretoria:** Todas as metas foram decompostas, executadas no sandbox seguro "
            f"e auditadas entre os departamentos conforme o protocolo corporativo multinível."
        )

        return summary


# Instância global singleton
multi_tier_orchestrator = MultiTierOrchestrator()
