"""
Suíte de Testes Automatizados — Sandboxed File System Tools & Agent Manipulation (AIOX / AgentOffice 2D)
Testa identificação de pastas e arquivos, visualização em árvore, busca por nome (find),
busca por conteúdo (grep), edição cirúrgica, renomeação/movimentação, cópia, exclusão,
barreiras de segurança contra path traversal, tool calling e comandos CLI dos agentes.
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from backend.app import app
from backend.models import Agent, AgentRoleType, AgentTier
from backend.orchestrator import orchestrator
from backend.orchestrator_multi_tier import multi_tier_orchestrator
from backend.storage import storage
from backend.tools.filesystem import (
    SecuritySandboxError,
    _get_workspace_dir,
    fs_copy,
    fs_create_directory,
    fs_delete_path,
    fs_edit_file,
    fs_file_info,
    fs_find_files,
    fs_list_directory,
    fs_read_file,
    fs_rename_or_move,
    fs_search_content,
    fs_tree_view,
    fs_write_file,
)


def run_all_filesystem_tests():
    print("=======================================================")
    print("INICIANDO SUÍTE DE TESTES: SANDBOXED FILE SYSTEM TOOLS")
    print("=======================================================\n")

    # Criar pasta temporária isolada como sandbox para os testes
    test_sandbox = Path(tempfile.mkdtemp(prefix="agentoffice_fs_test_"))
    
    try:
        # Configurar storage temporário apontando para o sandbox
        config = storage.load_config()
        original_ws = config.workspace_dir
        config.workspace_dir = str(test_sandbox)
        storage.save_config(config)

        # ---------------------------------------------------------------------
        # 1. Testando Criação e Listagem de Pastas & Arquivos
        # ---------------------------------------------------------------------
        print("--- 1. Testando Criação e Listagem de Pastas & Arquivos ---")
        asyncio.run(fs_create_directory("src/services", workspace_dir=str(test_sandbox)))
        asyncio.run(fs_create_directory("src/models", workspace_dir=str(test_sandbox)))
        asyncio.run(fs_create_directory("docs", workspace_dir=str(test_sandbox)))

        assert (test_sandbox / "src" / "services").is_dir(), "src/services deve existir"
        assert (test_sandbox / "src" / "models").is_dir(), "src/models deve existir"
        print("  -> Pastas criadas com sucesso!")

        # Gravar arquivos
        asyncio.run(fs_write_file(
            "src/models/user.py",
            "class User:\n    def __init__(self, name: str):\n        self.name = name\n",
            workspace_dir=str(test_sandbox)
        ))
        asyncio.run(fs_write_file(
            "src/services/auth.py",
            "from src.models.user import User\n\ndef authenticate(token: str) -> bool:\n    return token == 'secret'\n",
            workspace_dir=str(test_sandbox)
        ))
        asyncio.run(fs_write_file(
            "README.md",
            "# Projeto Teste\nDocumentação do sistema.\n",
            workspace_dir=str(test_sandbox)
        ))

        list_out = asyncio.run(fs_list_directory(".", workspace_dir=str(test_sandbox)))
        assert "README.md" in list_out, "README.md deve constar na listagem"
        assert "src" in list_out, "src deve constar na listagem"
        print("  -> fs_list_directory validado com sucesso!")

        # ---------------------------------------------------------------------
        # 2. Testando Visualização em Árvore (fs_tree_view)
        # ---------------------------------------------------------------------
        print("\n--- 2. Testando Visualização em Árvore (fs_tree_view) ---")
        tree_out = asyncio.run(fs_tree_view(".", max_depth=4, workspace_dir=str(test_sandbox)))
        assert "📁" in tree_out, "Árvore deve conter ícones de pastas"
        assert "📄" in tree_out, "Árvore deve conter ícones de arquivos"
        assert "services" in tree_out, "services deve aparecer na árvore"
        assert "auth.py" in tree_out, "auth.py deve aparecer na árvore"
        print("  -> fs_tree_view validado com sucesso:\n" + "\n".join("     " + l for l in tree_out.splitlines()[:8]))

        # ---------------------------------------------------------------------
        # 3. Testando Leitura de Arquivo com Fatiamento e Linhas Numeradas
        # ---------------------------------------------------------------------
        print("\n--- 3. Testando Leitura com Linhas Numeradas (fs_read_file) ---")
        read_numbered = asyncio.run(fs_read_file(
            "src/services/auth.py",
            show_line_numbers=True,
            start_line=1,
            end_line=3,
            workspace_dir=str(test_sandbox)
        ))
        assert "1 | from src.models.user import User" in read_numbered, "Deve conter linha 1 numerada"
        assert "2 |" in read_numbered, "Deve conter linha 2 numerada"
        print("  -> Leitura fatiada com numeração validada com sucesso!")

        # ---------------------------------------------------------------------
        # 4. Testando Identificação e Busca por Nome/Glob (fs_find_files)
        # ---------------------------------------------------------------------
        print("\n--- 4. Testando Localização de Arquivos por Glob (fs_find_files) ---")
        find_py = asyncio.run(fs_find_files("*.py", workspace_dir=str(test_sandbox)))
        assert "user.py" in find_py, "user.py deve ser encontrado"
        assert "auth.py" in find_py, "auth.py deve ser encontrado"
        assert "README.md" not in find_py, "README.md não deve bater com *.py"
        print("  -> fs_find_files (*.py) validado com sucesso!")

        # ---------------------------------------------------------------------
        # 5. Testando Busca por Conteúdo/Grep (fs_search_content)
        # ---------------------------------------------------------------------
        print("\n--- 5. Testando Busca por Conteúdo/Grep (fs_search_content) ---")
        grep_res = asyncio.run(fs_search_content("authenticate", workspace_dir=str(test_sandbox)))
        assert "auth.py:3" in grep_res, "Deve apontar auth.py na linha 3"
        assert "def authenticate" in grep_res, "Deve conter o snippet da função"
        print("  -> fs_search_content validado com sucesso!")

        # ---------------------------------------------------------------------
        # 6. Testando Metadados e Informações (fs_file_info)
        # ---------------------------------------------------------------------
        print("\n--- 6. Testando Metadados Técnicos (fs_file_info) ---")
        info_file = asyncio.run(fs_file_info("src/services/auth.py", workspace_dir=str(test_sandbox)))
        assert "Tamanho:" in info_file, "Deve reportar tamanho"
        assert "Quality Gate AST: ✅ Válido" in info_file, "Deve validar sintaxe Python válida"

        info_dir = asyncio.run(fs_file_info("src", workspace_dir=str(test_sandbox)))
        assert "Informações do Diretório" in info_dir, "Deve identificar pasta"
        assert "Subdiretórios diretos: 2" in info_dir, "Deve contar 2 subdiretórios (services e models)"
        print("  -> fs_file_info para arquivos e pastas validado com sucesso!")

        # ---------------------------------------------------------------------
        # 7. Testando Edição Cirúrgica de Código (fs_edit_file)
        # ---------------------------------------------------------------------
        print("\n--- 7. Testando Edição Cirúrgica de Código (fs_edit_file) ---")
        edit_res = asyncio.run(fs_edit_file(
            path="src/services/auth.py",
            target_text="return token == 'secret'",
            replacement_text="return token.startswith('bearer_') and len(token) > 10",
            workspace_dir=str(test_sandbox)
        ))
        assert "editado com sucesso" in edit_res, "Edição deve ter sucesso"
        assert "AST validado sem erros" in edit_res, "Deve manter sintaxe AST válida"

        updated_auth = (test_sandbox / "src/services/auth.py").read_text(encoding="utf-8")
        assert "bearer_" in updated_auth, "Código atualizado deve conter o novo trecho"
        assert "from src.models.user import User" in updated_auth, "Import inicial não deve ser perdido"
        print("  -> fs_edit_file cirúrgico validado com sucesso!")

        # ---------------------------------------------------------------------
        # 8. Testando Renomeação e Movimentação (fs_rename_or_move)
        # ---------------------------------------------------------------------
        print("\n--- 8. Testando Mover e Renomear (fs_rename_or_move) ---")
        move_res = asyncio.run(fs_rename_or_move(
            source_path="src/models/user.py",
            target_path="src/models/account.py",
            workspace_dir=str(test_sandbox)
        ))
        assert "movido/renomeado com sucesso" in move_res
        assert not (test_sandbox / "src/models/user.py").exists(), "Arquivo antigo não deve mais existir"
        assert (test_sandbox / "src/models/account.py").exists(), "Novo arquivo deve existir"
        print("  -> fs_rename_or_move validado com sucesso!")

        # ---------------------------------------------------------------------
        # 9. Testando Cópia de Arquivo e Pasta (fs_copy)
        # ---------------------------------------------------------------------
        print("\n--- 9. Testando Cópia de Arquivos (fs_copy) ---")
        copy_res = asyncio.run(fs_copy(
            source_path="src/models/account.py",
            target_path="src/models/account_backup.py",
            workspace_dir=str(test_sandbox)
        ))
        assert "copiado com sucesso" in copy_res
        assert (test_sandbox / "src/models/account_backup.py").exists()
        print("  -> fs_copy validado com sucesso!")

        # ---------------------------------------------------------------------
        # 10. Testando Exclusão de Arquivos e Pastas (fs_delete_path)
        # ---------------------------------------------------------------------
        print("\n--- 10. Testando Exclusão (fs_delete_path) ---")
        del_file_res = asyncio.run(fs_delete_path(
            "src/models/account_backup.py",
            workspace_dir=str(test_sandbox)
        ))
        assert "removido com sucesso" in del_file_res
        assert not (test_sandbox / "src/models/account_backup.py").exists()

        # Exclusão recursiva de pasta docs
        del_dir_res = asyncio.run(fs_delete_path("docs", recursive=True, workspace_dir=str(test_sandbox)))
        assert "removido com sucesso" in del_dir_res
        assert not (test_sandbox / "docs").exists()
        print("  -> fs_delete_path validado com sucesso!")

        # ---------------------------------------------------------------------
        # 11. Testando Barreiras de Segurança (Security Sandbox)
        # ---------------------------------------------------------------------
        print("\n--- 11. Testando Barreiras de Segurança contra Path Traversal ---")
        traversal_caught = False
        try:
            asyncio.run(fs_read_file("../../../secret.env", workspace_dir=str(test_sandbox)))
        except SecuritySandboxError:
            traversal_caught = True
        assert traversal_caught, "Tentativa de ler fora do sandbox deve ser barrada com SecuritySandboxError"

        root_delete_caught = False
        try:
            asyncio.run(fs_delete_path(".", workspace_dir=str(test_sandbox)))
        except SecuritySandboxError:
            root_delete_caught = True
        assert root_delete_caught, "Tentativa de deletar a raiz do sandbox deve ser terminantemente rejeitada"
        print("  -> Barreiras de segurança contra path traversal e deleção indevida aprovadas!")

        # ---------------------------------------------------------------------
        # 12. Testando Tool Calling através do Orquestrador (_execute_tool)
        # ---------------------------------------------------------------------
        print("\n--- 12. Testando Tool Calling no Orquestrador ---")
        test_agent = Agent(
            id="agent-fs-test",
            name="Dex",
            title="Senior Developer",
            role_type=AgentRoleType.WORKER,
            tier=AgentTier.WORKER,
            desk_id="desk_1"
        )
        ws_data = storage.load_workspace()

        # Testar execução de fs_tree_view via tool call
        tree_tool_res = asyncio.run(orchestrator._execute_tool(
            "fs_tree_view", {"path": "."}, test_agent, ws_data
        ))
        assert "📁" in tree_tool_res, "Tool call fs_tree_view deve retornar árvore"

        # Testar execução de fs_edit_file via tool call
        edit_tool_res = asyncio.run(orchestrator._execute_tool(
            "fs_edit_file",
            {
                "path": "README.md",
                "target_text": "Documentação do sistema.",
                "replacement_text": "Documentação completa atualizada pelo agente Dex."
            },
            test_agent,
            ws_data
        ))
        assert "editado com sucesso" in edit_tool_res
        print("  -> Execução de ferramentas via tool calling do agente aprovada!")

        # ---------------------------------------------------------------------
        # 13. Testando Comandos CLI no Chat (*ls, *tree, *cat, *find, *grep)
        # ---------------------------------------------------------------------
        print("\n--- 13. Testando Comandos CLI no Chat (*ls, *tree, *cat, etc.) ---")
        handled = asyncio.run(orchestrator._handle_aiox_command(test_agent, "*ls", ws_data))
        assert handled, "*ls deve ser tratado como comando AIOX"

        handled_tree = asyncio.run(orchestrator._handle_aiox_command(test_agent, "*tree", ws_data))
        assert handled_tree, "*tree deve ser tratado com sucesso"

        handled_cat = asyncio.run(orchestrator._handle_aiox_command(test_agent, "*cat README.md", ws_data))
        assert handled_cat, "*cat deve exibir arquivo"

        handled_find = asyncio.run(orchestrator._handle_aiox_command(test_agent, "*find *.py", ws_data))
        assert handled_find, "*find deve localizar arquivos"

        handled_grep = asyncio.run(orchestrator._handle_aiox_command(test_agent, "*grep bearer_", ws_data))
        assert handled_grep, "*grep deve buscar nos arquivos"
        print("  -> Comandos CLI de arquivos no chat dos agentes validados com sucesso!")

        # ---------------------------------------------------------------------
        # 14. Testando Comandos CLI no Sudo Agent Pax
        # ---------------------------------------------------------------------
        print("\n--- 14. Testando Comandos CLI de Arquivos no Sudo Agent Pax ---")
        sudo_agent = Agent(
            id="agent-sudo",
            name="Pax (@aiox-master)",
            title="Diretor Geral",
            role_type=AgentRoleType.SUPERVISOR,
            tier=AgentTier.SUDO,
            desk_id="desk_sudo"
        )
        squads_data = storage.load_squads()
        sudo_ls = asyncio.run(multi_tier_orchestrator._handle_sudo_aiox_command(
            sudo_agent, "*ls", squads_data.squads, ws_data
        ))
        assert "README.md" in sudo_ls, "Sudo Agent deve listar arquivos"

        sudo_tree = asyncio.run(multi_tier_orchestrator._handle_sudo_aiox_command(
            sudo_agent, "*tree", squads_data.squads, ws_data
        ))
        assert "📁" in sudo_tree, "Sudo Agent deve obter visualização em árvore"
        print("  -> Comandos CLI no Sudo Agent Pax validados com sucesso!")

        # ---------------------------------------------------------------------
        # 15. Testando Endpoints REST /api/workspace/...
        # ---------------------------------------------------------------------
        print("\n--- 15. Testando Endpoints REST da API de Arquivos ---")
        client = TestClient(app)

        # GET /api/workspace/files?mode=tree
        r_tree = client.get("/api/workspace/files?mode=tree")
        assert r_tree.status_code == 200
        assert "tree" in r_tree.json()

        # GET /api/workspace/file?path=README.md
        r_file = client.get("/api/workspace/file?path=README.md&show_line_numbers=true")
        assert r_file.status_code == 200
        assert "Dex" in r_file.json()["content"]

        # POST /api/workspace/file/edit
        r_edit = client.post("/api/workspace/file/edit", json={
            "path": "README.md",
            "target_text": "Dex",
            "replacement_text": "Aria & Dex"
        })
        assert r_edit.status_code == 200
        assert r_edit.json()["success"] is True

        # GET /api/workspace/search?query=Aria
        r_search = client.get("/api/workspace/search?query=Aria")
        assert r_search.status_code == 200
        assert "README.md" in r_search.json()["output"]

        # GET /api/workspace/info?path=src/services/auth.py
        r_info = client.get("/api/workspace/info?path=src/services/auth.py")
        assert r_info.status_code == 200
        assert "Quality Gate AST" in r_info.json()["info"]

        # POST /api/workspace/directory
        r_mkdir = client.post("/api/workspace/directory", json={"path": "src/controllers"})
        assert r_mkdir.status_code == 200

        # POST /api/workspace/copy
        r_cp = client.post("/api/workspace/copy", json={
            "source_path": "README.md",
            "target_path": "README.copy.md"
        })
        assert r_cp.status_code == 200

        # DELETE /api/workspace/file
        r_del = client.delete("/api/workspace/file?path=README.copy.md")
        assert r_del.status_code == 200
        print("  -> Endpoints REST do workspace sandbox aprovados!")

        print("\n=======================================================")
        print("TODOS OS TESTES DE SISTEMA DE ARQUIVOS PASSARAM COM 100% SUCESSO!")
        print("=======================================================")

    finally:
        # Restaurar configuração original de workspace
        if 'original_ws' in locals():
            cfg = storage.load_config()
            cfg.workspace_dir = original_ws
            storage.save_config(cfg)

        # Limpeza da pasta temporária
        if test_sandbox.exists():
            shutil.rmtree(test_sandbox, ignore_errors=True)


if __name__ == "__main__":
    run_all_filesystem_tests()
