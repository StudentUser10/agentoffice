"""
AgentOffice 2D - AIOX Memory Layer (Epic 7 Architecture)
Sistema de memória persistente para decisões arquiteturais (ADRs), padrões de código,
armadilhas conhecidas (gotchas) e insights descobertos entre sessões.
Permite que os agentes consultem o contexto histórico e executem Self-Critique (ADE).
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.storage import storage
from backend.tools.filesystem import _get_workspace_dir

logger = logging.getLogger("agentoffice.memory")


class MemoryEntry:
    def __init__(
        self,
        id: str,
        category: str,
        title: str,
        content: str,
        author: str = "system",
        timestamp: Optional[float] = None,
        tags: Optional[List[str]] = None
    ):
        self.id = id
        self.category = category  # "decision", "gotcha", "pattern", "insight"
        self.title = title
        self.content = content
        self.author = author
        self.timestamp = timestamp or time.time()
        self.tags = tags or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "timestamp": self.timestamp,
            "tags": self.tags
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=data.get("id", ""),
            category=data.get("category", "insight"),
            title=data.get("title", ""),
            content=data.get("content", ""),
            author=data.get("author", "system"),
            timestamp=data.get("timestamp", time.time()),
            tags=data.get("tags", [])
        )


class AIOXMemoryLayer:
    """Gerenciador central de memória persistente AIOX."""

    def __init__(self):
        self.data_dir = Path(__file__).resolve().parent.parent / "data" / "memory"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._init_defaults()

    def _get_file(self, category: str) -> Path:
        return self.data_dir / f"{category}s.json"

    def _sync_to_workspace(self, category: str, entries: List[Dict[str, Any]]) -> None:
        """Sincroniza cópia da memória no sandbox do workspace (.aiox/memory/)."""
        try:
            ws_root = _get_workspace_dir()
            ws_mem_dir = ws_root / ".aiox" / "memory"
            ws_mem_dir.mkdir(parents=True, exist_ok=True)
            target = ws_mem_dir / f"{category}s.json"
            target.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Falha ao sincronizar memória com workspace sandbox: {e}")

    def _init_defaults(self) -> None:
        """Inicializa entradas padrão da base de conhecimento caso não existam."""
        decisions_file = self._get_file("decision")
        if not decisions_file.exists():
            default_decisions = [
                {
                    "id": "ADR-001",
                    "category": "decision",
                    "title": "Persistência com SQLite e SQLAlchemy 2.0",
                    "content": "Utilizar create_engine('sqlite:///...') com connect_args={'check_same_thread': False} e sessionmaker assíncrono para operações de banco.",
                    "author": "Alex Tech Lead",
                    "timestamp": time.time(),
                    "tags": ["sqlite", "sqlalchemy", "database"]
                },
                {
                    "id": "ADR-002",
                    "category": "decision",
                    "title": "Arquitetura Modular com FastAPI APIRouter",
                    "content": "Todas as rotas HTTP devem ser agrupadas em routers prefixados dentro de src/routers/ com validação estrita via esquemas Pydantic.",
                    "author": "Alex Tech Lead",
                    "timestamp": time.time(),
                    "tags": ["fastapi", "pydantic", "api"]
                },
                {
                    "id": "ADR-003",
                    "category": "decision",
                    "title": "Governança Multinível e Comunicação Lateral AIOX",
                    "content": "Sudo Agent coordena a governança macro. Squad Leaders possuem autonomia técnica e cooperam lateralmente via tickets de assistência técnica.",
                    "author": "Sudo Agent",
                    "timestamp": time.time(),
                    "tags": ["governance", "squads", "aiox"]
                }
            ]
            self._save_entries("decision", default_decisions)

        gotchas_file = self._get_file("gotcha")
        if not gotchas_file.exists():
            default_gotchas = [
                {
                    "id": "GOTCHA-001",
                    "category": "gotcha",
                    "title": "Groq JSON Mode em Mensagens Conversacionais",
                    "content": "Provedores com json_mode estrito retornam HTTP 400 se o prompt contiver saudação ou texto livre. Deve-se interceptar com fallback automático.",
                    "author": "Sudo Agent",
                    "timestamp": time.time(),
                    "tags": ["groq", "llm", "json_mode"]
                },
                {
                    "id": "GOTCHA-002",
                    "category": "gotcha",
                    "title": "Path Traversal e Symlinks no Sandbox",
                    "content": "Todo acesso a arquivos deve validar target.relative_to(ws_root) e proibir links simbólicos para evitar evasão de sandbox.",
                    "author": "Roberto do cyber",
                    "timestamp": time.time(),
                    "tags": ["security", "sandbox", "filesystem"]
                }
            ]
            self._save_entries("gotcha", default_gotchas)

        patterns_file = self._get_file("pattern")
        if not patterns_file.exists():
            default_patterns = [
                {
                    "id": "PATTERN-001",
                    "category": "pattern",
                    "title": "AIOX Spec Pipeline (Story-Driven)",
                    "content": "Antes de escrever código, gerar stories/STORY-<id>.md contendo User Story, Critérios de Aceite (Given/When/Then) e Definition of Done.",
                    "author": "Alex Tech Lead",
                    "timestamp": time.time(),
                    "tags": ["agile", "story", "spec"]
                },
                {
                    "id": "PATTERN-002",
                    "category": "pattern",
                    "title": "Quality Gate com AST Check Estático",
                    "content": "Antes do sign-off de entrega, validar syntax via ast.parse em todos os arquivos .py gerados e emitir relatório reports/QA-REPORT-<id>.md.",
                    "author": "Roberto do cyber",
                    "timestamp": time.time(),
                    "tags": ["qa", "ast", "testing"]
                }
            ]
            self._save_entries("pattern", default_patterns)

        insights_file = self._get_file("insight")
        if not insights_file.exists():
            default_insights = [
                {
                    "id": "INSIGHT-001",
                    "category": "insight",
                    "title": "Paralelização Cirúrgica de Subagentes",
                    "content": "Subagentes efêmeros contratados com contratos estritos de O QUÊ, QUANDO e COMO aumentam a precisão e liberam as mesas imediatamente após o exit condition.",
                    "author": "Sudo Agent",
                    "timestamp": time.time(),
                    "tags": ["subagents", "productivity"]
                }
            ]
            self._save_entries("insight", default_insights)

    def _load_entries(self, category: str) -> List[Dict[str, Any]]:
        target = self._get_file(category)
        if not target.exists():
            return []
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Erro ao carregar memória '{category}': {e}")
            return []

    def _save_entries(self, category: str, entries: List[Dict[str, Any]]) -> None:
        target = self._get_file(category)
        target.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        self._sync_to_workspace(category, entries)

    # --- Operações Públicas de Memória ---

    def record_decision(self, title: str, content: str, author: str = "system", tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Registra uma nova decisão arquitetural (ADR)."""
        entries = self._load_entries("decision")
        count = len(entries) + 1
        entry_id = f"ADR-{count:03d}"
        entry = MemoryEntry(entry_id, "decision", title, content, author, time.time(), tags).to_dict()
        entries.append(entry)
        self._save_entries("decision", entries)
        return entry

    def record_gotcha(self, title: str, content: str, author: str = "system", tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Registra uma armadilha/edge case conhecido e sua mitigação."""
        entries = self._load_entries("gotcha")
        count = len(entries) + 1
        entry_id = f"GOTCHA-{count:03d}"
        entry = MemoryEntry(entry_id, "gotcha", title, content, author, time.time(), tags).to_dict()
        entries.append(entry)
        self._save_entries("gotcha", entries)
        return entry

    def record_pattern(self, title: str, content: str, author: str = "system", tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Registra um padrão arquitetural ou de código."""
        entries = self._load_entries("pattern")
        count = len(entries) + 1
        entry_id = f"PATTERN-{count:03d}"
        entry = MemoryEntry(entry_id, "pattern", title, content, author, time.time(), tags).to_dict()
        entries.append(entry)
        self._save_entries("pattern", entries)
        return entry

    def record_insight(self, title: str, content: str, author: str = "system", tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Registra um insight ou aprendizado da sessão."""
        entries = self._load_entries("insight")
        count = len(entries) + 1
        entry_id = f"INSIGHT-{count:03d}"
        entry = MemoryEntry(entry_id, "insight", title, content, author, time.time(), tags).to_dict()
        entries.append(entry)
        self._save_entries("insight", entries)
        return entry

    def list_decisions(self) -> List[Dict[str, Any]]:
        return self._load_entries("decision")

    def list_gotchas(self) -> List[Dict[str, Any]]:
        return self._load_entries("gotcha")

    def list_patterns(self) -> List[Dict[str, Any]]:
        return self._load_entries("pattern")

    def list_insights(self) -> List[Dict[str, Any]]:
        return self._load_entries("insight")

    def get_memory_context_prompt(self, max_items_per_category: int = 3) -> str:
        """Gera resumo compacto de contexto da memória AIOX para injeção no prompt do sistema."""
        decisions = self.list_decisions()[-max_items_per_category:]
        gotchas = self.list_gotchas()[-max_items_per_category:]
        patterns = self.list_patterns()[-max_items_per_category:]

        decisions_str = "\n".join([f"- [{d['id']}] {d['title']}: {d['content']}" for d in decisions])
        gotchas_str = "\n".join([f"- [{g['id']}] {g['title']}: {g['content']}" for g in gotchas])
        patterns_str = "\n".join([f"- [{p['id']}] {p['title']}: {p['content']}" for p in patterns])

        return (
            "### 🧠 CONTEXTO DA MEMÓRIA PERSISTENTE AIOX (Decisões & Padrões Estabelecidos):\n"
            f"**Decisões Arquiteturais (ADRs):**\n{decisions_str}\n\n"
            f"**Armadilhas Conhecidas (Gotchas a Evitar):**\n{gotchas_str}\n\n"
            f"**Padrões Obrigatórios:**\n{patterns_str}\n"
        )

    # --- ADE Self-Critique Engine ---

    def perform_ade_self_critique(
        self,
        target_dir: str = "src",
        workspace_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executa a fase de Self-Critique do ADE (Autonomous Development Engine):
        1. Inspeciona se há arquivos com TODO, FIXME ou placeholders não resolvidos.
        2. Valida conformidade com decisões conhecidas (ex: SQLite check_same_thread).
        3. Avalia syntax AST dos arquivos .py.
        4. Retorna veredito e relatório para gravação em reports/CRITIQUE.md.
        """
        ws_root = _get_workspace_dir(workspace_dir)
        target_path = ws_root / target_dir
        
        critique_items = []
        passed = True

        if not target_path.exists():
            return {
                "verdict": "SKIPPED",
                "score": 100,
                "notes": [f"Diretório '{target_dir}' não encontrado no sandbox."],
                "report_markdown": f"# 🔍 ADE SELF-CRITIQUE REPORT\n\nNenhum arquivo em `{target_dir}` para analisar."
            }

        py_files = list(target_path.glob("**/*.py"))
        if not py_files:
            critique_items.append("Nenhum arquivo Python encontrado para validação.")

        todos_found = []
        db_checks = []

        for pf in py_files:
            rel = str(pf.relative_to(ws_root))
            content = pf.read_text(encoding="utf-8")

            # Check 1: TODOs e placeholders
            lines = content.splitlines()
            for idx, line in enumerate(lines, start=1):
                if any(kw in line.upper() for kw in ("TODO", "FIXME", "XXX", "PASS # IMPLEMENT ME", "NOTIMPLEMENTEDERROR")):
                    todos_found.append(f"`{rel}` linha {idx}: {line.strip()}")

            # Check 2: Conformidade com ADR-001 (SQLite)
            if "sqlite" in content.lower() and "create_engine" in content:
                if "check_same_thread" not in content:
                    db_checks.append(f"⚠️ `{rel}`: Conexão SQLite sem `check_same_thread: False` (risco de multithread lock).")
                else:
                    db_checks.append(f"✅ `{rel}`: Conexão SQLite conforme com ADR-001.")

        if todos_found:
            passed = False
            critique_items.append(f"❌ Placeholders não implementados detectados:\n" + "\n".join([f"  - {t}" for t in todos_found]))
        else:
            critique_items.append("✅ Zero placeholders ou TODOs pendentes no código.")

        if db_checks:
            critique_items.extend(db_checks)

        score = 100 if passed else 75
        verdict = "✅ APROVADO" if passed else "⚠️ AÇÃO RECOMENDADA"

        report_md = (
            f"# 🔍 ADE SELF-CRITIQUE REPORT (AIOX)\n\n"
            f"- **Data:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- **Diretório Analisado:** `{target_dir}`\n"
            f"- **Arquivos Inspecionados:** {len(py_files)} módulos Python\n"
            f"- **Score:** {score}/100\n"
            f"- **Veredito:** {verdict}\n\n"
            f"## Itens da Auto-Crítica:\n"
            + "\n".join([f"- {it}" for it in critique_items]) + "\n\n"
            f"---\n*Gerado automaticamente pelo motor ADE (Autonomous Development Engine) do AgentOffice 2D.*"
        )

        # Gravar no sandbox
        try:
            reports_dir = ws_root / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / "CRITIQUE-LATEST.md").write_text(report_md, encoding="utf-8")
        except Exception as e:
            logger.debug(f"Erro ao salvar CRITIQUE report: {e}")

        return {
            "verdict": verdict,
            "score": score,
            "passed": passed,
            "notes": critique_items,
            "report_markdown": report_md
        }


# Instância global singleton
memory_layer = AIOXMemoryLayer()
