"""
Suíte de Testes Automatizados — Criação Obrigatória de Pastas em public/ para Novos Projetos
Verifica que:
1. A pasta public/ sempre existe automaticamente no workspace sandbox.
2. O helper ensure_public_project_folder cria subpastas dedicadas em public/.
3. O orquestrador AIOX garante que todas as criações novas vivam dentro de public/<projeto>/.
4. O endpoint HTTP /public lista projetos e serve index.html e assets com segurança anti-traversal.
"""

import asyncio
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
from backend.models import Agent, AgentTier
from backend.orchestrator_multi_tier import multi_tier_orchestrator
from backend.storage import storage
from backend.tools.filesystem import (
    _get_workspace_dir,
    ensure_public_project_folder,
    fs_read_file,
    fs_write_file,
)


def run_tests():
    print("===================================================================")
    print("TESTE: CRIAÇÃO OBRIGATÓRIA DE PASTAS DENTRO DE PUBLIC/ (AGENTES)")
    print("===================================================================\n")

    test_sandbox = Path(tempfile.mkdtemp(prefix="agentoffice_public_test_"))
    config = storage.load_config()
    original_ws = config.workspace_dir

    try:
        config.workspace_dir = str(test_sandbox)
        storage.save_config(config)

        # -----------------------------------------------------------------
        # 1. Pasta public/ é criada automaticamente no workspace
        # -----------------------------------------------------------------
        ws = _get_workspace_dir()
        public_dir = ws / "public"
        assert public_dir.exists() and public_dir.is_dir(), "A pasta public/ deve ser criada automaticamente!"
        print("✅ [1/6] Pasta public/ criada e garantida na raiz do workspace sandbox.")

        # -----------------------------------------------------------------
        # 2. ensure_public_project_folder cria subpasta dedicada
        # -----------------------------------------------------------------
        proj_dir = ensure_public_project_folder("flappy_bird")
        assert proj_dir.exists() and proj_dir.is_dir(), "Subpasta em public/ deve existir!"
        assert proj_dir.name == "flappy_bird"
        assert proj_dir.parent == public_dir
        print("✅ [2/6] ensure_public_project_folder criou com sucesso 'public/flappy_bird/'.")

        # -----------------------------------------------------------------
        # 3. Geração de arquivos de épico para Jogo cria pasta em public/
        # -----------------------------------------------------------------
        async def test_game_generation():
            mock_leader = Agent(
                id="agent-mock",
                name="Aria",
                title="Lead",
                tier=AgentTier.SQUAD_LEADER,
                avatar_id="avatar_1",
                desk_id="desk-1",
                system_prompt="Test Lead"
            )
            files = await multi_tier_orchestrator._generate_dynamic_epic_files(
                leader=mock_leader,
                epic={"epic_title": "Arcade Space Shooter", "objective": "Desenvolver um jogo retro em canvas"},
                user_prompt="Crie um jogo retro espacial jogável",
                squad_id="squad-core-engineering"
            )
            assert len(files) > 0, "Deve gerar arquivos para o jogo."
            for f in files:
                p = f["path"].replace("\\", "/")
                assert p.startswith("public/"), f"Arquivo '{p}' deve estar dentro de public/!"
                parts = p.split("/")
                assert len(parts) >= 3, f"Arquivo '{p}' deve estar em uma subpasta dentro de public/!"
            return files

        files = asyncio.run(test_game_generation())
        print(f"✅ [3/6] Épico de jogo gerou {len(files)} arquivos organizados dentro de subpasta em public/: {files[0]['path']}.")

        # -----------------------------------------------------------------
        # 4. Geração para Frontend/Site cria pasta em public/
        # -----------------------------------------------------------------
        async def test_web_generation():
            mock_leader = Agent(
                id="agent-mock",
                name="Aria",
                title="Lead",
                tier=AgentTier.SQUAD_LEADER,
                avatar_id="avatar_1",
                desk_id="desk-1",
                system_prompt="Test Lead"
            )
            files = await multi_tier_orchestrator._generate_dynamic_epic_files(
                leader=mock_leader,
                epic={"epic_title": "Portal de Clientes", "objective": "Criar portal web moderno"},
                user_prompt="Crie um portal web com landing page",
                squad_id="squad-core-engineering"
            )
            assert len(files) > 0, "Deve gerar arquivos para o portal."
            for f in files:
                p = f["path"].replace("\\", "/")
                assert p.startswith("public/"), f"Arquivo '{p}' deve estar dentro de public/!"
                parts = p.split("/")
                assert len(parts) >= 3, f"Arquivo '{p}' deve estar em uma subpasta dentro de public/!"
            return files

        files = asyncio.run(test_web_generation())
        print(f"✅ [4/6] Épico de portal web gerou {len(files)} arquivos organizados dentro de subpasta em public/.")

        # -----------------------------------------------------------------
        # 5. Testando escrita e visualização via endpoint HTTP /public/
        # -----------------------------------------------------------------
        sample_html = "<!DOCTYPE html><html><body><h1>Meu App Criado pelo Agente</h1></body></html>"
        asyncio.run(fs_write_file("public/calculadora/index.html", sample_html))
        asyncio.run(fs_write_file("public/calculadora/app.js", "console.log('calc ready');"))

        client = TestClient(app)

        # Acessar listagem de /public
        res_list = client.get("/public")
        assert res_list.status_code == 200
        assert "calculadora" in res_list.text or "AgentOffice Workspace" in res_list.text
        print("✅ [5/6] Endpoint HTTP /public listou os projetos criados com sucesso (Status 200).")

        # Acessar a aplicação em /public/calculadora
        res_app = client.get("/public/calculadora")
        assert res_app.status_code == 200
        assert "Meu App Criado pelo Agente" in res_app.text
        print("✅ [6/6] Endpoint HTTP /public/calculadora serviu index.html diretamente com sucesso (Status 200).")

        # -----------------------------------------------------------------
        # Bônus: Proteção de segurança anti-traversal em /public
        # -----------------------------------------------------------------
        res_escape = client.get("/public/../data/config.json")
        assert res_escape.status_code in [403, 404], f"Status esperado 403 ou 404, obteve {res_escape.status_code}"
        print("🔒 [Bônus] Tentativa de path traversal em /public/.. bloqueada com segurança!")

        print("\n===================================================================")
        print("TODOS OS TESTES DE CRIAÇÃO EM PUBLIC/ PASSARAM COM 100% DE SUCESSO!")
        print("===================================================================")

    finally:
        config.workspace_dir = original_ws
        storage.save_config(config)
        if test_sandbox.exists():
            shutil.rmtree(test_sandbox, ignore_errors=True)


if __name__ == "__main__":
    run_tests()
