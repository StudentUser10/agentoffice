"""
AgentOffice 2D - Ponto de Entrada Principal
Inicia o servidor local FastAPI e abre o navegador automaticamente.
"""

import sys
import threading
import time
import webbrowser
from pathlib import Path

# Verify Python version >= 3.10
if sys.version_info < (3, 10):
    print("ERRO: O AgentOffice 2D requer Python 3.10 ou superior.")
    sys.exit(1)

# Ensure console supports UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import uvicorn
from backend.config import DEFAULT_HOST, DEFAULT_PORT
from backend.storage import storage

BANNER = """
===================================================================
                   AGENTOFFICE 2D - v0.1.0                         
         Escritorio Visual em Pixel Art para Agentes de IA         
===================================================================
"""


def open_browser():
    """Opens browser at the local server address after a brief delay."""
    time.sleep(1.2)
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    print(f"\n[+] Abrindo {url} no seu navegador...")
    webbrowser.open(url)


def main():
    # Print welcome banner
    print(BANNER)
    print(f"[+] Inicializando arquivos de persistência...")
    storage.ensure_initial_data()
    print(f"[+] Dados prontos em: {storage.data_dir}")
    print(f"[+] Servidor local escutando em: http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"[+] Pressione Ctrl+C para encerrar o aplicativo.\n")

    # Launch browser opener in background thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Start Uvicorn server (bound strictly to 127.0.0.1 for security)
    uvicorn.run(
        "backend.app:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        log_level="info",
        reload=False
    )


if __name__ == "__main__":
    main()
