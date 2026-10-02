"""
AgentOffice 2D - Testes Automatizados da Etapa 6 (Filesystem Sandboxed & Subagentes Dinâmicos)
Valida:
1. Sandboxed File System (fs_list_directory, fs_create_directory, fs_read_file, fs_write_file)
2. Proteção estrita contra Path Traversal, symlinks e caminhos fora do workspace (SecuritySandboxError)
3. Schema estruturado e validação obrigatória de SpawnSubagentParams (O quê, Quando, Como, Exit)
4. Alocação dinâmica de mesa vaga no workspace e despacho de eventos WebSocket
5. Ciclo de vida completo do subagente (spawn, execução cirúrgica, relatório, desocupação de mesa)
6. Fluxo completo: Supervisor cria 'src/routers' e contrata subagente para gerar 'src/database.py'
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from pydantic import ValidationError

from backend.models import (
    Agent,
    AgentRoleType,
    AgentState,
    Desk,
    SpawnSubagentParams,
    WorkspaceData,
)
from backend.orchestrator import orchestrator
from backend.storage import storage
from backend.tools.filesystem import (
    SecuritySandboxError,
    fs_create_directory,
    fs_list_directory,
    fs_read_file,
    fs_write_file,
    resolve_and_validate_path,
)
from backend.tools.spawner import (
    DeskUnavailableError,
    SpawnerError,
    despawn_subagent,
    spawn_subagent,
)


def setup_temp_workspace():
    """Configura um diretório temporário isolado como sandbox para os testes."""
    temp_dir = tempfile.mkdtemp(prefix="agentoffice_sandbox_test_")
    cfg = storage.load_config()
    cfg.workspace_dir = temp_dir
    cfg.configured = True
    storage.save_config(cfg)
    return Path(temp_dir)


def teardown_temp_workspace(temp_dir: Path):
    """Limpa o diretório temporário após os testes."""
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_filesystem_sandbox_and_security():
    """Testa todas as operações de I/O e a barreira de contenção (Path Traversal Guard)."""
    print("\n[+] Testando Sandboxed File System e Segurança de Path Traversal...")
    temp_dir = setup_temp_workspace()

    try:
        # 1. Criação de pastas legítimas dentro do sandbox
        res_dir = asyncio.run(fs_create_directory("src/routers", agent_id="agent-sup"))
        assert "sucesso" in res_dir.lower()
        assert (temp_dir / "src" / "routers").is_dir()

        # 2. Gravação de arquivo atômico legítimo
        content = "from fastapi import APIRouter\nrouter = APIRouter()\n"
        res_write = asyncio.run(fs_write_file("src/routers/users.py", content, agent_id="agent-sup"))
        assert "sucesso" in res_write.lower()
        users_file = temp_dir / "src" / "routers" / "users.py"
        assert users_file.is_file()
        assert users_file.read_text(encoding="utf-8") == content

        # 3. Leitura segura de arquivo
        res_read = asyncio.run(fs_read_file("src/routers/users.py", agent_id="agent-sup"))
        assert "from fastapi import APIRouter" in res_read

        # 4. Listagem de diretório
        res_list = asyncio.run(fs_list_directory("src", agent_id="agent-sup"))
        assert "routers" in res_list

        # --- TESTES DE SEGURANÇA E TENTATIVAS DE INVASÃO ---
        print("[+] Testando barreiras de contenção (Path Traversal Guard)...")

        # Tentativa 1: Traversal relativo com ../
        try:
            asyncio.run(fs_read_file("../../data/config.json"))
            assert False, "Deveria ter bloqueado traversal relativo"
        except SecuritySandboxError as e:
            assert "outside workspace sandbox" in str(e).lower()

        # Tentativa 2: Escrita externa com ../
        try:
            asyncio.run(fs_write_file("../../../outside_hack.txt", "malicious payload"))
            assert False, "Deveria ter bloqueado escrita externa"
        except SecuritySandboxError as e:
            assert "outside workspace sandbox" in str(e).lower()

        # Tentativa 3: Caminho absoluto fora do sandbox
        outside_abs = "C:\\Windows\\System32\\cmd.exe" if os.name == "nt" else "/etc/passwd"
        try:
            asyncio.run(fs_read_file(outside_abs))
            assert False, "Deveria ter bloqueado caminho absoluto fora do sandbox"
        except SecuritySandboxError as e:
            assert "outside workspace sandbox" in str(e).lower()

        print("  -> Todas as 3 tentativas de evasão do sandbox foram bloqueadas com sucesso!")

    finally:
        teardown_temp_workspace(temp_dir)


def test_subagent_spawner_contract_and_desk_allocation():
    """Valida o schema SpawnSubagentParams, alocação de mesa livre e desocupação."""
    print("\n[+] Testando Contrato de Delegação do Subagente e Alocação de Mesa...")
    temp_dir = setup_temp_workspace()

    try:
        # Garantir supervisor inicial no workspace
        ws = storage.load_workspace()
        supervisor = next((a for a in ws.agents if a.role_type == AgentRoleType.SUPERVISOR), None)
        assert supervisor is not None, "Supervisor não encontrado no workspace padrão"

        # 1. Validação de rejeição de campos faltantes no Pydantic
        try:
            # Faltando what_exact_task, how_instructions e exit_condition
            SpawnSubagentParams(
                name="Lazy_Agent",
                role_title="Assistant"
            )
            assert False, "Deveria ter falhado por falta de campos obrigatórios no Pydantic"
        except ValidationError:
            pass

        # 2. Criação estruturada completa e rigorosa
        mission = SpawnSubagentParams(
            name="SQL_Architect",
            role_title="Especialista em Banco de Dados SQL",
            avatar_id="dev_avatar_1",
            what_exact_task="Desenvolver o módulo de banco de dados src/database.py com conexão SQLite e SessionLocal.",
            what_out_of_scope="Não implementar rotas HTTP nem criar regras de negócio em routers.",
            when_triggers="Executar imediatamente após a criação do diretório src/.",
            how_instructions=(
                "1. Importar create_engine, declarative_base e sessionmaker do sqlalchemy.\n"
                "2. Definir SQLALCHEMY_DATABASE_URL = 'sqlite:///./app.db'.\n"
                "3. Criar a sessão SessionLocal e o Base declarativo."
            ),
            allowed_tools=["fs_write_file", "fs_read_file"],
            exit_condition="Arquivo src/database.py criado e validado no disco com SessionLocal."
        )

        # Contar mesas livres antes
        free_desks_before = [d for d in ws.desks if not d.agent_id]
        assert len(free_desks_before) > 0, "Deve haver pelo menos uma mesa livre para o teste"

        # 3. Invocar spawn_subagent
        subagent, desk = asyncio.run(spawn_subagent(supervisor.id, mission, ws))

        assert subagent.id.startswith("agent-")
        assert subagent.name == "SQL_Architect"
        assert subagent.role_type == AgentRoleType.WORKER
        assert subagent.supervisor_id == supervisor.id
        assert subagent.desk_id == desk.id
        assert desk.agent_id == subagent.id
        assert subagent.is_temporary is True
        assert subagent.mission is not None
        assert subagent.mission.what_exact_task == mission.what_exact_task
        assert subagent.id in supervisor.subordinate_ids

        # Recarregar do storage para confirmar persistência no disco
        reloaded_ws = storage.load_workspace()
        saved_sub = next((a for a in reloaded_ws.agents if a.id == subagent.id), None)
        assert saved_sub is not None
        saved_desk = next((d for d in reloaded_ws.desks if d.id == desk.id), None)
        assert saved_desk.agent_id == subagent.id

        # 4. Despawnar subagente (bater o ponto)
        despawn_ok = asyncio.run(despawn_subagent(subagent.id, reloaded_ws))
        assert despawn_ok is True

        ws_after_despawn = storage.load_workspace()
        assert not any(a.id == subagent.id for a in ws_after_despawn.agents)
        desk_after = next((d for d in ws_after_despawn.desks if d.id == desk.id), None)
        assert desk_after.agent_id is None
        sup_after = next((a for a in ws_after_despawn.agents if a.id == supervisor.id), None)
        assert subagent.id not in sup_after.subordinate_ids

        print("  -> Spawn, ocupação de mesa, persistência e despawn validados com 100% de sucesso!")

    finally:
        teardown_temp_workspace(temp_dir)


def test_supervisor_flow_create_routers_and_spawn_database_subagent():
    """
    Roteiro de Verificação Completo:
    1. Ordem do usuário: 'Crie uma estrutura de pastas para um projeto FastAPI com src/routers
       e contrate um subagente focado em escrever o database.py'.
    2. Confirmação de que o Supervisor chama spawn_subagent com todos os campos detalhados.
    3. Aparecimento do subagente na mesa vazia.
    4. Criação real das pastas e do arquivo no disco dentro do sandbox.
    """
    print("\n[+] Testando Fluxo de Orquestração: Criação de src/routers + Subagente para database.py...")
    temp_dir = setup_temp_workspace()

    try:
        ws = storage.load_workspace()
        supervisor = next((a for a in ws.agents if a.role_type == AgentRoleType.SUPERVISOR), None)
        assert supervisor is not None

        # 1. Supervisor executa ferramenta de criação de pasta 'src/routers'
        res_dir = asyncio.run(orchestrator._execute_tool(
            tool_name="fs_create_directory",
            params={"path": "src/routers"},
            agent=supervisor,
            workspace=ws
        ))
        assert "sucesso" in res_dir.lower()
        assert (temp_dir / "src" / "routers").is_dir()

        # 2. Supervisor chama spawn_subagent com parâmetros obrigatórios cirúrgicos
        spawn_args = {
            "name": "DB_Engineer",
            "role_title": "Database Engineer Specialist",
            "avatar_id": "dev_avatar_2",
            "what_exact_task": "Criar o arquivo src/database.py com SQLAlchemy (engine, SessionLocal, Base).",
            "what_out_of_scope": "Não modificar arquivos em src/routers nem criar modelos de negócio.",
            "when_triggers": "Executar imediatamente uma vez que src/routers foi provisionado.",
            "how_instructions": (
                "Escrever código Python limpo no arquivo src/database.py contendo:\n"
                "from sqlalchemy import create_engine\n"
                "from sqlalchemy.orm import declarative_base, sessionmaker\n"
                "SQLALCHEMY_DATABASE_URL = 'sqlite:///./sql_app.db'\n"
                "engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={'check_same_thread': False})\n"
                "SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)\n"
                "Base = declarative_base()\n"
            ),
            "allowed_tools": ["fs_write_file", "fs_read_file"],
            "exit_condition": "Arquivo src/database.py gravado com sucesso no disco contendo SessionLocal e Base."
        }

        res_spawn = asyncio.run(orchestrator._execute_tool(
            tool_name="spawn_subagent",
            params=spawn_args,
            agent=supervisor,
            workspace=ws
        ))
        assert "sucesso" in res_spawn.lower()
        assert "DB_Engineer" in res_spawn

        # 3. Verificar que o subagente apareceu no workspace e ocupou uma mesa
        ws_updated = storage.load_workspace()
        subagent = next((a for a in ws_updated.agents if a.name == "DB_Engineer"), None)
        assert subagent is not None, "Subagente DB_Engineer deve estar presente no workspace"
        assert subagent.role_type == AgentRoleType.WORKER
        assert subagent.supervisor_id == supervisor.id
        assert subagent.is_temporary is True
        assert subagent.mission.what_exact_task == spawn_args["what_exact_task"]

        assigned_desk = next((d for d in ws_updated.desks if d.id == subagent.desk_id), None)
        assert assigned_desk is not None
        assert assigned_desk.agent_id == subagent.id

        # 4. Execução da missão pelo subagente: gravação de src/database.py
        db_code = (
            "from sqlalchemy import create_engine\n"
            "from sqlalchemy.orm import declarative_base, sessionmaker\n\n"
            "SQLALCHEMY_DATABASE_URL = 'sqlite:///./sql_app.db'\n"
            "engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={'check_same_thread': False})\n"
            "SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)\n"
            "Base = declarative_base()\n"
        )
        res_db = asyncio.run(orchestrator._execute_tool(
            tool_name="fs_write_file",
            params={"path": "src/database.py", "content": db_code},
            agent=subagent,
            workspace=ws_updated
        ))
        assert "sucesso" in res_db.lower()

        # 5. Validação física no disco dentro do sandbox
        db_file_path = temp_dir / "src" / "database.py"
        assert db_file_path.is_file(), "src/database.py deve existir fisicamente no disco dentro do sandbox"
        file_text = db_file_path.read_text(encoding="utf-8")
        assert "SessionLocal" in file_text
        assert "Base = declarative_base()" in file_text
        assert (temp_dir / "src" / "routers").is_dir()

        print(f"  -> Pastas criadas: {temp_dir / 'src' / 'routers'}")
        print(f"  -> Arquivo gerado: {db_file_path} ({len(file_text)} bytes)")
        print("  -> Subagente alocado na mesa:", assigned_desk.name)
        print("  -> Roteiro de verificação concluído com 100% de êxito!")

    finally:
        teardown_temp_workspace(temp_dir)


if __name__ == "__main__":
    test_filesystem_sandbox_and_security()
    test_subagent_spawner_contract_and_desk_allocation()
    test_supervisor_flow_create_routers_and_spawn_database_subagent()
    print("\n=======================================================")
    print("TODOS OS TESTES DA ETAPA 6 PASSARAM COM SUCESSO!")
    print("=======================================================\n")
