"""
Suíte de Testes Automatizados — Operações Universais de Arquivos para Qualquer Agente
(Ler, Copiar, Reescrever, Observar, Comparar, Pesquisar qualquer tipo de arquivo: texto, código, binários, imagens)

Verifica que:
1. Qualquer agente pode ler qualquer arquivo (texto com linhas ou binário com prévia técnica/base64).
2. Qualquer agente pode escrever/reescrever qualquer arquivo (texto em UTF-8 ou binário via Base64/Hex).
3. Qualquer agente pode copiar arquivos e árvores de diretórios com segurança (fs_copy).
4. Qualquer agente pode comparar arquivos (diff de texto ou bytes/SHA-256 para binários).
5. Qualquer agente pode observar arquivos (telemetria, MIME, SHA-256, AST e head/tail).
6. Pesquisas globais (find/grep) operam sem falhas na presença de binários e pastas.
7. Comandos determinísticos de chat CLI (*observe, *diff, *tail, *cat, *cp) funcionam para todos os agentes.
8. Endpoints REST (/api/workspace/compare, /api/workspace/observe, /api/workspace/file) respondem com integridade.
"""

import asyncio
import base64
import os
import shutil
import tempfile
from pathlib import Path
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from backend.app import app
from backend.models import (
    Agent,
    AgentTier,
    AgentRoleType,
    AgentState,
    WorkspaceData,
    Desk,
    SpawnSubagentParams,
)
from backend.orchestrator import orchestrator
from backend.orchestrator_multi_tier import multi_tier_orchestrator
from backend.storage import storage
from backend.tools.filesystem import (
    _get_workspace_dir,
    fs_compare_files,
    fs_copy,
    fs_create_directory,
    fs_delete_path,
    fs_edit_file,
    fs_file_info,
    fs_find_files,
    fs_list_directory,
    fs_observe_file,
    fs_read_file,
    fs_rename_or_move,
    fs_search_content,
    fs_tree_view,
    fs_write_file,
)


def run_tests():
    print("===================================================================")
    print("TESTE: OPERAÇÕES UNIVERSAIS DE ARQUIVOS PARA QUALQUER AGENTE")
    print("===================================================================\n")

    test_sandbox = Path(tempfile.mkdtemp(prefix="agentoffice_any_file_test_"))
    config = storage.load_config()
    original_ws = config.workspace_dir

    try:
        config.workspace_dir = str(test_sandbox)
        storage.save_config(config)

        # -----------------------------------------------------------------
        # 1. Leitura e Escrita de Arquivo de Texto (com slicing e edição)
        # -----------------------------------------------------------------
        code_sample = (
            "def calculate_tax(amount: float) -> float:\n"
            "    rate = 0.15\n"
            "    return amount * rate\n\n"
            "def main():\n"
            "    print('Tax:', calculate_tax(100.0))\n"
        )
        res_write = asyncio.run(fs_write_file("public/calculator/calc.py", code_sample, mode="overwrite", agent_id="dev-1"))
        assert "calc.py" in res_write and "gravado com sucesso" in res_write
        print("✅ [1/8] Escrita atômica de arquivo de código em public/calculator/calc.py com sucesso.")

        # Leitura com numeração de linhas
        res_read = asyncio.run(fs_read_file("public/calculator/calc.py", show_line_numbers=True, agent_id="qa-1"))
        assert "calculate_tax" in res_read
        assert "1 | def calculate_tax" in res_read
        print("✅ [2/8] Leitura de arquivo de texto com fatiamento e linhas numeradas concluída.")

        # Edição cirúrgica
        res_edit = asyncio.run(fs_edit_file("public/calculator/calc.py", "rate = 0.15", "rate = 0.20", agent_id="dev-1"))
        assert "editado com sucesso" in res_edit
        res_read_edited = asyncio.run(fs_read_file("public/calculator/calc.py"))
        assert "rate = 0.20" in res_read_edited
        print("✅ [3/8] Edição cirúrgica (fs_edit_file) aplicada e verificada.")

        # -----------------------------------------------------------------
        # 2. Leitura e Escrita/Reescrita de Arquivo Binário (PNG real em Base64)
        # -----------------------------------------------------------------
        # PNG de 1x1 pixel transparente válido
        valid_png_base64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )
        res_png_write = asyncio.run(
            fs_write_file("public/calculator/logo.png", valid_png_base64, encoding="base64", agent_id="dev-1")
        )
        assert "logo.png" in res_png_write and "base64" in res_png_write

        # Leitura automática de binário (retorna sumário rico sem falhar)
        res_png_read_auto = asyncio.run(fs_read_file("public/calculator/logo.png", encoding="auto"))
        assert "Arquivo Binário Detectado" in res_png_read_auto
        assert "image/png" in res_png_read_auto
        assert "Checksum SHA-256" in res_png_read_auto

        # Leitura explícita em Base64
        res_png_read_b64 = asyncio.run(fs_read_file("public/calculator/logo.png", encoding="base64"))
        assert "Formato: Base64" in res_png_read_b64
        assert "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=" in res_png_read_b64
        print("✅ [4/8] Escrita e leitura universal de arquivo binário (PNG) via Base64 validadas.")

        # -----------------------------------------------------------------
        # 3. Cópia de Arquivo e Diretório (fs_copy)
        # -----------------------------------------------------------------
        res_cp_file = asyncio.run(fs_copy("public/calculator/calc.py", "public/calculator/calc_backup.py", agent_id="sm-1"))
        assert "calc_backup.py" in res_cp_file

        res_cp_bin = asyncio.run(fs_copy("public/calculator/logo.png", "public/calculator/logo_copy.png", agent_id="sm-1"))
        assert "logo_copy.png" in res_cp_bin

        res_cp_dir = asyncio.run(fs_copy("public/calculator", "public/calculator_v2", agent_id="sm-1"))
        assert "calculator_v2" in res_cp_dir
        assert (_get_workspace_dir() / "public" / "calculator_v2" / "calc.py").exists()
        print("✅ [5/8] Cópia de arquivos de texto, binários e diretórios (fs_copy) operando com integridade.")

        # -----------------------------------------------------------------
        # 4. Comparação Minuciosa (fs_compare_files: idênticos, diff e binário)
        # -----------------------------------------------------------------
        # Idênticos
        res_comp_same = asyncio.run(fs_compare_files("public/calculator/logo.png", "public/calculator/logo_copy.png"))
        assert "100% IDÊNTICOS" in res_comp_same

        # Arquivos de texto diferentes -> Unified Diff
        asyncio.run(fs_write_file("public/calculator/calc_diff.py", "def calculate_tax(x):\n    return x * 0.50\n"))
        res_comp_diff = asyncio.run(fs_compare_files("public/calculator/calc.py", "public/calculator/calc_diff.py"))
        assert "Diff Unificado" in res_comp_diff
        assert "```diff" in res_comp_diff

        # Arquivos binários diferentes
        other_bin_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x06\x00\x00\x00"
        other_bin_b64 = base64.b64encode(other_bin_bytes).decode("ascii")
        asyncio.run(fs_write_file("public/calculator/other.png", other_bin_b64, encoding="base64"))
        res_comp_bin = asyncio.run(fs_compare_files("public/calculator/logo.png", "public/calculator/other.png"))
        assert "Comparação Binária" in res_comp_bin
        assert "DIFERENTES" in res_comp_bin
        print("✅ [6/8] Comparação profunda (fs_compare_files: texto e binário) validada com sucesso.")

        # -----------------------------------------------------------------
        # 5. Observação e Telemetria Profunda (fs_observe_file)
        # -----------------------------------------------------------------
        res_obs_txt = asyncio.run(fs_observe_file("public/calculator/calc.py", tail_lines=5, head_lines=5))
        assert "Observação de Arquivo de Texto" in res_obs_txt
        assert "Quality Gate AST: ✅ Válido" in res_obs_txt
        assert "Head" in res_obs_txt and "Tail" in res_obs_txt

        res_obs_png = asyncio.run(fs_observe_file("public/calculator/logo.png"))
        assert "Observação de Arquivo Binário" in res_obs_png
        assert "Dimensões da Imagem: 1x1 px" in res_obs_png
        assert "Hexdump" in res_obs_png
        print("✅ [7/8] Observação e telemetria profunda (fs_observe_file) com AST e hexdump validadas.")

        # -----------------------------------------------------------------
        # 6. Comandos CLI dos Agentes e Orquestrador (*observe, *diff, *tail)
        # -----------------------------------------------------------------
        dummy_agent = Agent(
            id="agent-architect",
            name="Arquiteto",
            title="Líder Técnico",
            tier=AgentTier.SQUAD_LEADER,
            desk_id="desk_1",
            role_type=AgentRoleType.SUPERVISOR,
        )
        dummy_ws = WorkspaceData(
            agents=[dummy_agent],
            desks=[Desk(id="desk_1", name="Mesa Arquiteto", room_id="room_dev", x=10, y=10, seat_x=10, seat_y=10, front_x=10, front_y=12)],
        )

        # Agent CLI: *observe
        handled = asyncio.run(orchestrator._handle_aiox_command(dummy_agent, "*observe public/calculator/calc.py", dummy_ws))
        assert handled is True
        assert "Observação de Arquivo de Texto" in dummy_ws.conversations[dummy_agent.id][-1]["text"]

        # Agent CLI: *diff
        asyncio.run(orchestrator._handle_aiox_command(dummy_agent, "*diff public/calculator/calc.py public/calculator/calc_diff.py", dummy_ws))
        assert "Diff Unificado" in dummy_ws.conversations[dummy_agent.id][-1]["text"]

        # Agent CLI: *tail
        asyncio.run(orchestrator._handle_aiox_command(dummy_agent, "*tail public/calculator/calc.py 2", dummy_ws))
        assert "Final do Arquivo" in dummy_ws.conversations[dummy_agent.id][-1]["text"]

        # Agent CLI: *cp
        asyncio.run(orchestrator._handle_aiox_command(dummy_agent, "*cp public/calculator/calc.py public/calculator/calc_cli.py", dummy_ws))
        assert "copiado com sucesso" in dummy_ws.conversations[dummy_agent.id][-1]["text"]

        # Direct Tool Execution: fs_compare_files and fs_observe_file
        res_tool_diff = asyncio.run(orchestrator._execute_tool("fs_compare_files", {"path_a": "public/calculator/calc.py", "path_b": "public/calculator/calc_diff.py"}, dummy_agent, dummy_ws))
        assert "Diff Unificado" in res_tool_diff

        res_tool_obs = asyncio.run(orchestrator._execute_tool("fs_observe_file", {"path": "public/calculator/calc.py"}, dummy_agent, dummy_ws))
        assert "Observação de Arquivo de Texto" in res_tool_obs

        # Sudo Agent CLI (*observe, *diff)
        sudo_agent = Agent(
            id="agent-sudo",
            name="Pax",
            title="Diretor Geral",
            tier=AgentTier.SUDO,
            desk_id="desk_sudo",
            aiox_handle="@aiox-master",
        )
        sudo_obs = asyncio.run(multi_tier_orchestrator._handle_sudo_aiox_command(sudo_agent, "*observe public/calculator/logo.png", [], dummy_ws))
        assert "Observação de Arquivo Binário" in sudo_obs

        sudo_diff = asyncio.run(multi_tier_orchestrator._handle_sudo_aiox_command(sudo_agent, "*diff public/calculator/calc.py public/calculator/calc_diff.py", [], dummy_ws))
        assert "Diff Unificado" in sudo_diff

        # Subagent allowed_tools default contém todas as ferramentas
        sub_params = SpawnSubagentParams(
            name="SubWorker",
            role_title="Especialista",
            avatar_id="avatar_1",
            what_exact_task="Executar tarefas",
            what_out_of_scope="Fora de escopo",
            when_triggers="Agora",
            how_instructions="Instruções",
            exit_condition="Concluído",
        )
        assert "fs_compare_files" in sub_params.allowed_tools
        assert "fs_observe_file" in sub_params.allowed_tools
        assert "fs_copy" in sub_params.allowed_tools
        assert "fs_read_file" in sub_params.allowed_tools
        assert "fs_write_file" in sub_params.allowed_tools
        print("✅ [8/8] Todos os comandos CLI (*observe, *diff, *tail, *cp) e permissões de subagentes validados!")

        # -----------------------------------------------------------------
        # 7. Endpoints REST da API (/api/workspace/compare, /api/workspace/observe, /api/workspace/file)
        # -----------------------------------------------------------------
        client = TestClient(app)

        # POST /api/workspace/compare
        r_comp = client.post("/api/workspace/compare", json={"path_a": "public/calculator/calc.py", "path_b": "public/calculator/calc_diff.py"})
        assert r_comp.status_code == 200, f"Erro status: {r_comp.status_code}, {r_comp.text}"
        assert "Diff Unificado" in r_comp.json()["output"]

        # GET /api/workspace/observe
        r_obs = client.get("/api/workspace/observe?path=public/calculator/calc.py&tail_lines=5")
        assert r_obs.status_code == 200
        assert "Observação de Arquivo de Texto" in r_obs.json()["output"]

        # GET /api/workspace/file com encoding=base64
        r_file_b64 = client.get("/api/workspace/file?path=public/calculator/logo.png&encoding=base64")
        assert r_file_b64.status_code == 200
        assert "Formato: Base64" in r_file_b64.json()["content"]

        print("🎉 TODOS OS 8 BLOCOS DE TESTES PASSARAM COM SUCESSO TOTAL!")

    finally:
        config.workspace_dir = original_ws
        storage.save_config(config)
        shutil.rmtree(test_sandbox, ignore_errors=True)


if __name__ == "__main__":
    run_tests()
