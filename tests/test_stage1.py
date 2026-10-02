"""
Testes automatizados da Etapa 1 do AgentOffice 2D
Verifica armazenamento atômico, integridade de configuração, segurança e endpoints da API.
"""

import sys
import json
import shutil
import tempfile
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient

from backend.app import app
from backend.models import AppConfig
from backend.storage import Storage


def test_storage_atomic_and_backups():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        store = Storage(data_dir=tmp_path)
        store.ensure_initial_data()

        config_file = tmp_path / "config.json"
        workspace_file = tmp_path / "workspace.json"

        assert config_file.exists(), "config.json deve ser criado automaticamente"
        assert workspace_file.exists(), "workspace.json deve ser criado automaticamente"

        # Test loading config
        cfg = store.load_config()
        assert cfg.provider == "ollama"
        assert cfg.configured is False

        # Test updating config with secret key
        cfg.api_keys["openai"] = "sk-secret-test-key-12345"
        cfg.configured = True
        store.save_config(cfg, backup=True)

        # Check that backup was created
        backups = list((tmp_path / "backups").glob("config_*.bak"))
        assert len(backups) > 0, "Backup de config.json deve ser gerado antes da alteração"

        # Check safe config view NEVER exposes the secret key
        safe_view = store.get_safe_config_view(cfg)
        assert safe_view.has_api_keys["openai"] is True
        assert not hasattr(safe_view, "api_keys") or "sk-secret" not in json.dumps(safe_view.model_dump())

        # Test corrupted config recovery
        with open(config_file, "w", encoding="utf-8") as f:
            f.write("{ INVALID JSON MALFORMED")

        # Loading should not crash and should preserve corrupt copy
        recovered = store.load_config()
        assert recovered is not None
        corrupt_copies = list(tmp_path.glob("config.json.corrupt.*"))
        assert len(corrupt_copies) > 0, "Cópia do arquivo corrompido deve ser preservada"


def test_api_endpoints():
    client = TestClient(app)

    # 1. Health check
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # 2. Serve index.html
    res = client.get("/")
    assert res.status_code == 200
    assert "AgentOffice 2D" in res.text

    # 3. GET /api/config (Safe view)
    res = client.get("/api/config")
    assert res.status_code == 200
    data = res.json()
    assert "provider" in data
    assert "has_api_keys" in data
    assert "api_keys" not in data, "Chaves de API NUNCA devem ser enviadas ao frontend"

    # 4. POST /api/config (Update configuration)
    update_data = {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "llama3:latest",
        "api_key": "sk-temp-testing-key",
        "configured": True
    }
    res = client.post("/api/config", json=update_data)
    assert res.status_code == 200
    saved_view = res.json()
    assert saved_view["configured"] is True
    assert "sk-temp-testing-key" not in json.dumps(saved_view), "Chave nunca pode vazar na resposta da API"
    assert saved_view["has_api_keys"]["ollama"] is True

    # 5. GET /api/config/detect-models (When Ollama is not running, must NOT crash)
    res = client.get("/api/config/detect-models")
    assert res.status_code == 200
    models_data = res.json()
    assert "available" in models_data
    assert isinstance(models_data["models"], list)

    # 6. POST /api/config/test-connection
    test_payload = {
        "provider": "ollama",
        "base_url": "http://127.0.0.1:9999"  # non-existent port
    }
    res = client.post("/api/config/test-connection", json=test_payload)
    assert res.status_code == 200
    test_res = res.json()
    assert test_res["success"] is False
    assert "details" in test_res


def test_security_host_validation():
    client = TestClient(app)
    # Request with malicious / unauthorized host
    res = client.get("/api/health", headers={"Host": "malicious-site.com"})
    assert res.status_code == 403
    assert "Host não permitido" in res.json()["error"]


if __name__ == "__main__":
    print("Executando test_storage_atomic_and_backups...")
    test_storage_atomic_and_backups()
    print("Executando test_api_endpoints...")
    test_api_endpoints()
    print("Executando test_security_host_validation...")
    test_security_host_validation()
    print("\nTODOS OS TESTES DA ETAPA 1 PASSARAM COM SUCESSO!")
