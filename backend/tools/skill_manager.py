"""
AgentOffice 2D - Claude Skills Manager & Execution Engine
Permite que o Sudo Agent Pax (@aiox-master) e seus subordinados (Aria, Dex, Quinn, Cipher, Echo, Morgan)
possam pesquisar, baixar de URLs (GitHub/web), instalar do catálogo do Claude e executar skills especializadas.
"""

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.config import DATA_DIR, SKILLS_DIR, SKILLS_REGISTRY_FILE
from backend.models import (
    Agent,
    AgentTier,
    ClaudeSkill,
    SkillAssignRequest,
    SkillInstallRequest,
    SkillRegistryData,
    Squad,
    WorkspaceData,
)
from backend.storage import storage
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.tools.skills")


# Catálogo Oficial de Claude Skills embutidas prontas para instalação imediata
CLAUDE_SKILLS_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "frontend-craftsman",
        "name": "Claude Frontend Craftsman",
        "description": "Especialista em interfaces web modernas, responsivas e visualmente ricas com HTML5 semântico, CSS avançado (glassmorphism, gradientes, tipografia moderna) e JavaScript nativo.",
        "version": "1.2.0",
        "author": "Anthropic Claude / Community",
        "category": "frontend",
        "tags": ["frontend", "html5", "css3", "ui", "ux", "responsive", "glassmorphism"],
        "allowed_roles": ["dev", "architect", "master"],
        "instructions": (
            "DIRETRIZES DA SKILL CLAUDE FRONTEND CRAFTSMAN:\n"
            "1. Crie interfaces web que impressionem visualmente (efeito 'WOW'): cores harmoniosas, contraste refinado e tipografia moderna (ex: Inter, Segoe UI, Roboto).\n"
            "2. Utilize Vanilla CSS rico: glassmorphism suave (backdrop-filter: blur(8px)), gradientes lineares sutis, bordas translúcidas (rgba(255,255,255,0.1)) e sombras multicamadas (box-shadow).\n"
            "3. Layouts 100% responsivos utilizando CSS Grid (repeat(auto-fit, minmax(...))) e Flexbox moderno.\n"
            "4. Adicione micro-interações elegantes em hover, active e focus em botões e cards.\n"
            "5. Estrutura semântica rigorosa: <header>, <nav>, <main>, <section>, <article>, <footer> e um único <h1> por página.\n"
            "6. JavaScript nativo limpo, modular, com listeners após DOMContentLoaded e sem dependências externas desnecessárias."
        )
    },
    {
        "id": "claude-code-architect",
        "name": "Claude System Architect",
        "description": "Engenharia de software de alta fidelidade: arquitetura limpa, separação de camadas (Clean Architecture), contratos tipados com Pydantic, resiliência assíncrona e desacoplamento de storage.",
        "version": "1.1.0",
        "author": "Anthropic Claude / Community",
        "category": "architecture",
        "tags": ["architecture", "clean-code", "solid", "rest", "pydantic", "asyncio"],
        "allowed_roles": ["architect", "master", "dev"],
        "instructions": (
            "DIRETRIZES DA SKILL CLAUDE SYSTEM ARCHITECT:\n"
            "1. Separação rigorosa de responsabilidades: Models (Pydantic), Routers/Controllers (HTTP), Services/Business Logic e Storage/Data Access.\n"
            "2. Proibido misturar lógica de banco de dados diretamente em endpoints de rota.\n"
            "3. Tipagem estática rigorosa em todas as assinaturas de funções e retornos assíncronos (async/await).\n"
            "4. Tratamento defensivo de exceções: capturar erros específicos, registrar logs com contexto e retornar status codes HTTP semanticamente corretos (200, 201, 400, 404, 422, 500).\n"
            "5. Código auto-documentado com docstrings em Markdown e comentários explicativos nas decisões não-triviais."
        )
    },
    {
        "id": "python-security-auditor",
        "name": "Python Security & OWASP Auditor",
        "description": "Hardening corporativo e auditoria estática contra OWASP Top 10: prevenção a SQL Injection, XSS, Path Traversal em sandboxes, sanitização de inputs e mitigação de DoS.",
        "version": "1.3.0",
        "author": "Anthropic Claude / Community",
        "category": "security",
        "tags": ["security", "owasp", "hardening", "audit", "sanitization", "rate-limiting"],
        "allowed_roles": ["sec", "master", "architect"],
        "instructions": (
            "DIRETRIZES DA SKILL PYTHON SECURITY AUDITOR:\n"
            "1. Sanitização obrigatória de todas as entradas de usuário utilizando escape HTML (html.escape) e remoção de caracteres de controle invisíveis.\n"
            "2. NUNCA execute concatenação de strings em comandos de sistema operacional (subprocess/os.system) ou queries SQL brutas. Use sempre ORMs ou query parameters parametrizados.\n"
            "3. Isolamento rigoroso de arquivos em Sandbox: valide se o caminho canônico do arquivo (Path.resolve()) reside obrigatoriamente dentro do diretório de workspace permitido.\n"
            "4. Imponha limites de taxa (Rate Limiting) e timeouts em chamadas externas para evitar exaustão de conexões ou negação de serviço (DoS).\n"
            "5. Bloqueie exposição de segredos, tokens ou senhas em logs ou retornos de APIs."
        )
    },
    {
        "id": "game-engine-2d",
        "name": "2D Canvas & Arcade Game Engine",
        "description": "Especialista em desenvolvimento de jogos 2D nativos: game loop estável em 60 FPS, detecção de colisão AABB, física vetorial (gravidade, aceleração, atrito), partículas e HUD de pontuação.",
        "version": "1.0.0",
        "author": "Anthropic Claude / Community",
        "category": "code",
        "tags": ["game", "canvas", "physics", "2d", "arcade", "collision", "gameloop"],
        "allowed_roles": ["dev", "master"],
        "instructions": (
            "DIRETRIZES DA SKILL 2D GAME ENGINE:\n"
            "1. Implemente o clássico loop de jogo desacoplado (update e render/draw) com base em requestAnimationFrame e cálculo de delta time (dt).\n"
            "2. Detecção de colisão eficiente: Axis-Aligned Bounding Box (AABB) ou cálculo de distância euclidiana para círculos/projéteis.\n"
            "3. Gerenciamento estruturado de entidades: Player, Inimigos/Obstáculos, Projéteis e Efeitos Particulados com arrays de vida útil.\n"
            "4. Suporte nativo a controles de teclado (WASD, setas, espaço) com captura suave de teclas pressionadas (key state dictionary).\n"
            "5. HUD em Canvas integrado exibindo pontuação, vidas restantes e tela de Game Over com botão de restart."
        )
    },
    {
        "id": "qa-quality-gatekeeper",
        "name": "Automated QA & ADE Quality Gatekeeper",
        "description": "Garantia de qualidade autônoma: inspeção via AST (Abstract Syntax Tree), cobertura de critérios de aceite (ACs), prevenção de TODOs/placeholders e auto-crítica ADE com score 100/100.",
        "version": "1.2.0",
        "author": "Anthropic Claude / Community",
        "category": "qa",
        "tags": ["qa", "ast", "testing", "quality-gate", "acceptance-criteria", "dod"],
        "allowed_roles": ["qa", "master", "sm"],
        "instructions": (
            "DIRETRIZES DA SKILL QA QUALITY GATEKEEPER:\n"
            "1. Todo arquivo Python gerado deve ser auditado via AST (ast.parse) antes de ser considerado pronto para entrega.\n"
            "2. Valide se a implementação atende a 100% dos Critérios de Aceite definidos na História AIOX.\n"
            "3. PROIBIDO aceitar código com comentários como '# TODO', '# placeholder' ou funções vazias que apenas contenham 'pass'.\n"
            "4. Verifique a conformidade com as ADRs (Decisões Arquiteturais) corporativas registradas na camada de memória.\n"
            "5. Emita relatórios formais em Markdown detalhando o veredito por arquivo e a nota final da auto-crítica (Score 100)."
        )
    },
    {
        "id": "api-doc-story-writer",
        "name": "Technical Documentation & Story Writer",
        "description": "Documentação técnica corporativa de alta precisão: especificações OpenAPI 3.0, redação de Histórias formais de desenvolvimento (AIOX Stories) e resumos executivos.",
        "version": "1.0.0",
        "author": "Anthropic Claude / Community",
        "category": "docs",
        "tags": ["docs", "openapi", "markdown", "stories", "spec", "architecture"],
        "allowed_roles": ["doc", "sm", "master"],
        "instructions": (
            "DIRETRIZES DA SKILL TECHNICAL DOCUMENTATION & STORY WRITER:\n"
            "1. Redija histórias no padrão AIOX contendo Contexto, Objetivo de Engenharia, Critérios de Aceite (ACs) numerados e Definition of Done (DoD).\n"
            "2. Crie documentações com exemplos claros de requisição (JSON payloads), respostas de sucesso e respostas de erro.\n"
            "3. Use tabelas em Markdown e diagramas conceituais estruturados para facilitar a leitura.\n"
            "4. Mantenha sincronizados os manuais de arquitetura com os arquivos reais existentes no sandbox do projeto."
        )
    },
    {
        "id": "scraping-data-extractor",
        "name": "Data Extraction & Web Scraping Specialist",
        "description": "Extração estruturada de dados da web: requisições HTTP seguras, parsing de HTML/JSON, rotação de headers (User-Agent), extração via Regex/Seletores e gravação em CSV/JSON no sandbox.",
        "version": "1.0.0",
        "author": "Anthropic Claude / Community",
        "category": "code",
        "tags": ["scraper", "data", "extraction", "parser", "httpx", "json"],
        "allowed_roles": ["dev", "master"],
        "instructions": (
            "DIRETRIZES DA SKILL DATA EXTRACTION & SCRAPING:\n"
            "1. Utilize headers HTTP realistas e respeite o robots.txt e limites de requisições por segundo.\n"
            "2. Valide e sanitize os dados extraídos antes de persistir em disco.\n"
            "3. Salve os resultados em JSON estruturado ou CSV bem formatado dentro do diretório sandbox autorizado.\n"
            "4. Isole o tratamento de erros para links quebrados ou payloads malformados sem derrubar o pipeline."
        )
    }
]


class ClaudeSkillManager:
    """Gerenciador central de Claude Skills com catálogo, download e injeção de contexto."""

    def __init__(self):
        self._ensure_dirs()
        self._init_registry()

    def _ensure_dirs(self) -> None:
        """Garante a existência das pastas de persistência de skills."""
        os.makedirs(SKILLS_DIR, exist_ok=True)

    def _init_registry(self) -> None:
        """Inicializa o registro de skills com as skills padrão caso ainda não exista."""
        if not SKILLS_REGISTRY_FILE.exists():
            initial_skills = []
            for item in CLAUDE_SKILLS_CATALOG:
                # Inicialmente instalar as principais skills essenciais
                skill = ClaudeSkill(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    version=item["version"],
                    author=item["author"],
                    category=item["category"],
                    tags=item["tags"],
                    instructions=item["instructions"],
                    allowed_roles=item["allowed_roles"],
                    assigned_to=["*"],  # Disponíveis globalmente para todos os squads
                    source="catalog",
                    enabled=True,
                    created_at=time.time()
                )
                initial_skills.append(skill)
                # Salvar arquivo SKILL.md
                self._save_skill_file(skill)

            registry = SkillRegistryData(skills=initial_skills)
            self._save_registry(registry)
            logger.info(f"[Skills] Registro inicializado com {len(initial_skills)} Claude Skills padrão.")

    def _load_registry(self) -> SkillRegistryData:
        """Carrega o registro de skills do disco."""
        if not SKILLS_REGISTRY_FILE.exists():
            self._init_registry()
        try:
            with open(SKILLS_REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return SkillRegistryData(**data)
        except Exception as e:
            logger.error(f"[Skills] Erro ao carregar registry.json: {e}")
            return SkillRegistryData()

    def _save_registry(self, registry: SkillRegistryData) -> None:
        """Salva o registro de skills atomicamente."""
        temp_file = SKILLS_REGISTRY_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(registry.model_dump(), f, indent=2, ensure_ascii=False)
        temp_file.replace(SKILLS_REGISTRY_FILE)

    def _save_skill_file(self, skill: ClaudeSkill) -> None:
        """Grava a skill em formato padrão Anthropic SKILL.md com frontmatter YAML."""
        skill_dir = SKILLS_DIR / skill.id
        os.makedirs(skill_dir, exist_ok=True)
        file_path = skill_dir / "SKILL.md"

        yaml_tags = ", ".join(skill.tags)
        yaml_roles = ", ".join(skill.allowed_roles)
        yaml_assigned = ", ".join(skill.assigned_to)

        content = (
            f"---\n"
            f"name: {skill.id}\n"
            f"title: {skill.name}\n"
            f"description: {skill.description}\n"
            f"version: {skill.version}\n"
            f"author: {skill.author}\n"
            f"category: {skill.category}\n"
            f"tags: [{yaml_tags}]\n"
            f"allowed_roles: [{yaml_roles}]\n"
            f"assigned_to: [{yaml_assigned}]\n"
            f"source: {skill.source}\n"
            f"---\n\n"
            f"# {skill.name}\n\n"
            f"{skill.instructions}\n"
        )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    def list_installed_skills(self) -> List[ClaudeSkill]:
        """Lista todas as skills instaladas no workspace."""
        registry = self._load_registry()
        return [s for s in registry.skills if s.enabled]

    def list_catalog(self) -> List[Dict[str, Any]]:
        """Retorna o catálogo completo de skills disponíveis para download/instalação."""
        installed_ids = {s.id for s in self.list_installed_skills()}
        catalog_items = []
        for item in CLAUDE_SKILLS_CATALOG:
            copy_item = dict(item)
            copy_item["is_installed"] = item["id"] in installed_ids
            catalog_items.append(copy_item)
        return catalog_items

    def get_skill(self, skill_id: str) -> Optional[ClaudeSkill]:
        """Obtém uma skill instalada pelo ID."""
        registry = self._load_registry()
        for s in registry.skills:
            if s.id == skill_id:
                return s
        return None

    async def download_or_install_skill(
        self,
        req: SkillInstallRequest,
        requester_agent_id: Optional[str] = None
    ) -> ClaudeSkill:
        """
        Baixa e instala uma nova Claude Skill a partir de URL, do Catálogo ou de especificações customizadas.
        """
        registry = self._load_registry()

        # Caso 1: Instalação via URL (GitHub raw, web server, etc.)
        if req.url:
            logger.info(f"[Skills] Baixando Claude Skill de URL: {req.url}")
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                res = await client.get(req.url)
                if res.status_code != 200:
                    raise ValueError(f"Falha ao baixar skill da URL (HTTP {res.status_code}): {res.text[:150]}")
                raw_text = res.text

            # Extrair frontmatter e corpo
            skill_id = req.skill_id or re.sub(r'[^a-zA-Z0-9_\-]', '', Path(req.url).stem.lower()) or f"skill_{int(time.time())}"
            name = req.name or skill_id.replace('-', ' ').title()
            description = req.description or "Claude Skill baixada via URL."
            category = req.category or "code"
            tags = req.tags or ["claude-skill", "downloaded"]
            instructions = raw_text

            # Se contiver frontmatter YAML (--- ... ---)
            fm_match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$", raw_text)
            if fm_match:
                fm_text, body_text = fm_match.group(1), fm_match.group(2)
                instructions = body_text.strip()
                for line in fm_text.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k, v = k.strip().lower(), v.strip()
                        if k == "title" or (k == "name" and not req.name):
                            name = v.strip("\"'")
                        elif k == "description" and not req.description:
                            description = v.strip("\"'")
                        elif k == "category":
                            category = v.strip("\"'")

            skill = ClaudeSkill(
                id=skill_id,
                name=name,
                description=description,
                version="1.0.0",
                author="Claude Web / GitHub",
                category=category,
                tags=tags,
                instructions=instructions,
                allowed_roles=["master", "architect", "dev", "qa", "sec", "doc", "sm"],
                assigned_to=req.assigned_to or ["*"],
                source="url",
                source_url=req.url,
                enabled=True,
                created_at=time.time()
            )

        # Caso 2: Instalação a partir do Catálogo embutido
        elif req.skill_id and any(item["id"] == req.skill_id for item in CLAUDE_SKILLS_CATALOG):
            item = next(item for item in CLAUDE_SKILLS_CATALOG if item["id"] == req.skill_id)
            skill = ClaudeSkill(
                id=item["id"],
                name=req.name or item["name"],
                description=req.description or item["description"],
                version=item["version"],
                author=item["author"],
                category=item["category"],
                tags=item["tags"],
                instructions=req.instructions or item["instructions"],
                allowed_roles=item["allowed_roles"],
                assigned_to=req.assigned_to or ["*"],
                source="catalog",
                enabled=True,
                created_at=time.time()
            )

        # Caso 3: Criação de Skill customizada direta
        elif req.name and req.instructions:
            skill_id = req.skill_id or re.sub(r'[^a-zA-Z0-9_\-]', '', req.name.lower().replace(' ', '-'))
            skill = ClaudeSkill(
                id=skill_id,
                name=req.name,
                description=req.description or "Skill customizada criada no AgentOffice.",
                version="1.0.0",
                author="AgentOffice User",
                category=req.category or "code",
                tags=req.tags or ["custom"],
                instructions=req.instructions,
                allowed_roles=["master", "architect", "dev", "qa", "sec", "doc", "sm"],
                assigned_to=req.assigned_to or ["*"],
                source="custom",
                enabled=True,
                created_at=time.time()
            )
        else:
            raise ValueError("Parâmetros insuficientes para instalar skill. Forneça URL, skill_id do catálogo ou nome e instruções.")

        # Atualizar ou adicionar ao registro
        existing_idx = next((i for i, s in enumerate(registry.skills) if s.id == skill.id), None)
        if existing_idx is not None:
            registry.skills[existing_idx] = skill
        else:
            registry.skills.append(skill)

        self._save_registry(registry)
        self._save_skill_file(skill)

        await hub.broadcast({
            "type": "skill.updated",
            "action": "installed",
            "skill": skill.model_dump()
        })

        logger.info(f"[Skills] Skill '{skill.id}' instalada com sucesso por {requester_agent_id or 'sistema'}.")
        return skill

    async def assign_skill(
        self,
        skill_id: str,
        target_id: str,
        action: str = "assign"
    ) -> ClaudeSkill:
        """
        Atribui ou revoga uma skill para um agente específico, um squad inteiro ou globalmente ('*').
        """
        registry = self._load_registry()
        skill = next((s for s in registry.skills if s.id == skill_id), None)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' não encontrada no registro.")

        if action == "assign":
            if target_id not in skill.assigned_to:
                skill.assigned_to.append(target_id)
        elif action == "unassign":
            if target_id in skill.assigned_to:
                skill.assigned_to.remove(target_id)

        self._save_registry(registry)
        self._save_skill_file(skill)

        # Se for agente ou squad, sincronizar também no workspace / squads.json
        try:
            workspace = storage.load_workspace()
            agent = next((a for a in workspace.agents if a.id == target_id or getattr(a, "aiox_handle", "") == target_id), None)
            if agent:
                if action == "assign" and skill_id not in agent.skills:
                    agent.skills.append(skill_id)
                elif action == "unassign" and skill_id in agent.skills:
                    agent.skills.remove(skill_id)
                storage.save_workspace(workspace)

            squads_data = storage.load_squads()
            squad = next((s for s in squads_data.squads if s.id == target_id or s.name.lower() == target_id.lower()), None)
            if squad:
                if action == "assign" and skill_id not in squad.skills:
                    squad.skills.append(skill_id)
                elif action == "unassign" and skill_id in squad.skills:
                    squad.skills.remove(skill_id)
                storage.save_squads(squads_data)
        except Exception as e:
            logger.warning(f"[Skills] Erro ao sincronizar atribuição em workspace/squads: {e}")

        await hub.broadcast_system_notice(
            f"⚡ [Claude Skills] Skill '{skill.name}' {'concedida a' if action == 'assign' else 'revogada de'} '{target_id}'."
        )
        await hub.broadcast({
            "type": "skill.updated",
            "action": "assigned",
            "skill_id": skill_id,
            "target_id": target_id
        })

        return skill

    async def remove_skill(self, skill_id: str) -> bool:
        """Remove uma skill instalada do workspace."""
        registry = self._load_registry()
        skill = next((s for s in registry.skills if s.id == skill_id), None)
        if not skill:
            return False

        registry.skills = [s for s in registry.skills if s.id != skill_id]
        self._save_registry(registry)

        # Remover pasta do disco
        skill_dir = SKILLS_DIR / skill_id
        if skill_dir.exists():
            shutil.rmtree(skill_dir, ignore_errors=True)

        await hub.broadcast_system_notice(
            f"⚡ [Claude Skills] A Skill '{skill.name}' ({skill_id}) foi removida do escritório."
        )
        await hub.broadcast({
            "type": "skill.updated",
            "action": "removed",
            "skill_id": skill_id
        })
        return True

    def can_agent_use_skill(self, agent: Agent, skill: ClaudeSkill, squad: Optional[Squad] = None) -> bool:
        """
        Verifica se o agente possui autorização para utilizar a skill.
        Regra: Sudo Agent Pax (@aiox-master) possui autoridade irrestrita.
        Subordinados utilizam caso a skill esteja atribuída globalmente ('*'),
        ao seu squad, ao seu ID individual, ou ao seu papel AIOX.
        """
        if not skill.enabled:
            return False

        # 1. Pax (@aiox-master) ou tier SUDO tem autoridade total
        if agent.tier == AgentTier.SUDO or getattr(agent, "aiox_role", "") == "master":
            return True

        # 2. Atribuição global
        if "*" in skill.assigned_to:
            return True

        # 3. Atribuição direta por ID do agente ou handle
        if agent.id in skill.assigned_to or getattr(agent, "aiox_handle", "") in skill.assigned_to:
            return True

        # 4. Atribuição pelo ID do squad
        squad_id = squad.id if squad else agent.squad_id
        if squad_id and squad_id in skill.assigned_to:
            return True

        # 5. Lista de skills do próprio agente ou squad
        if skill.id in agent.skills:
            return True
        if squad and skill.id in squad.skills:
            return True

        # 6. Compatibilidade de papel AIOX
        aiox_role = getattr(agent, "aiox_role", "")
        if aiox_role and aiox_role in skill.allowed_roles:
            return True

        return False

    def get_active_skills_for_agent(
        self,
        agent: Agent,
        squad: Optional[Squad] = None
    ) -> List[ClaudeSkill]:
        """Retorna todas as skills ativas e autorizadas para o agente."""
        installed = self.list_installed_skills()
        return [s for s in installed if self.can_agent_use_skill(agent, s, squad)]

    def inject_skills_into_prompt(
        self,
        agent: Agent,
        base_prompt: str,
        squad: Optional[Squad] = None,
        max_skills: int = 3
    ) -> str:
        """
        Injeta o corpo de instruções das Claude Skills ativas no system prompt do agente.
        """
        skills = self.get_active_skills_for_agent(agent, squad)
        if not skills:
            return base_prompt

        skills_block = "\n\n" + "=" * 60 + "\n"
        skills_block += "⚡ [CLAUDE SKILLS ATIVADAS PARA SUA EXECUÇÃO]\n"
        skills_block += f"O Diretor Geral Pax (@aiox-master) e a governança autorizaram as seguintes Claude Skills para você ({agent.name}):\n\n"

        for s in skills[:max_skills]:
            skills_block += f"### SKILL: {s.name} (v{s.version} — {s.category})\n"
            skills_block += f"{s.instructions.strip()}\n\n"

        skills_block += "=" * 60 + "\n"
        return base_prompt + skills_block

    async def auto_recommend_and_grant_skills(
        self,
        user_prompt: str,
        epic_title: str,
        leader: Agent,
        squad: Optional[Squad] = None
    ) -> List[ClaudeSkill]:
        """
        Inteligência de Pax (@aiox-master): analisa o épico do usuário e concede
        automaticamente as Claude Skills mais indicadas para o líder e seu squad.
        """
        lower = (user_prompt + " " + epic_title).lower()
        skills_to_grant = []

        # Detecção contextual de necessidade de skill
        if "site" in lower or "html" in lower or "css" in lower or "frontend" in lower or "showcase" in lower or "ui" in lower:
            skills_to_grant.append("frontend-craftsman")

        if "jogo" in lower or "game" in lower or "canvas" in lower or "arcade" in lower:
            skills_to_grant.append("game-engine-2d")

        if "seguran" in lower or "owasp" in lower or "vulnerab" in lower or "audit" in lower or "hardening" in lower:
            skills_to_grant.append("python-security-auditor")

        if "arquitetura" in lower or "microsservi" in lower or "clean" in lower or "solid" in lower or "api" in lower:
            skills_to_grant.append("claude-code-architect")

        if "scraping" in lower or "extra" in lower or "crawler" in lower or "coleta" in lower:
            skills_to_grant.append("scraping-data-extractor")

        if "qa" in lower or "teste" in lower or "ast" in lower or "qualidade" in lower:
            skills_to_grant.append("qa-quality-gatekeeper")

        if "documenta" in lower or "doc" in lower or "story" in lower or "openapi" in lower:
            skills_to_grant.append("api-doc-story-writer")

        granted = []
        for s_id in skills_to_grant:
            skill = self.get_skill(s_id)
            # Se a skill ainda não estiver instalada, instalar do catálogo automaticamente
            if not skill:
                try:
                    skill = await self.download_or_install_skill(SkillInstallRequest(skill_id=s_id), requester_agent_id="agent-sudo")
                except Exception as e:
                    logger.warning(f"[Skills] Não foi possível auto-instalar '{s_id}': {e}")
                    continue

            if skill:
                target_id = squad.id if squad else leader.id
                if target_id not in skill.assigned_to and "*" not in skill.assigned_to:
                    await self.assign_skill(skill.id, target_id, "assign")
                granted.append(skill)

        if granted:
            names = ", ".join([f"'{s.name}'" for s in granted])
            target_name = squad.name if squad else leader.name
            await hub.broadcast_system_notice(
                f"👑 [AIOX:MASTER] Pax (@aiox-master) autorizou e concedeu as Claude Skills [{names}] para {target_name}!"
            )

        return granted


# Instância singleton global do gerenciador de skills
skill_manager = ClaudeSkillManager()
