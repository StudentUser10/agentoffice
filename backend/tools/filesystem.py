"""
AgentOffice 2D - Sandboxed File System Tools (Etapa 6)
Operações assíncronas de arquivos e diretórios protegidas por sandbox estrito.
Impede estritamente path traversal (..), acesso fora do workspace_dir e symlinks.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from backend.storage import storage
from backend.websocket_hub import hub

logger = logging.getLogger("agentoffice.tools.filesystem")


class SecuritySandboxError(Exception):
    """Exceção levantada quando um agente tenta violar os limites do workspace sandbox."""
    pass


def _get_workspace_dir(override_dir: Optional[str] = None) -> Path:
    """Obtém e valida o diretório de trabalho raiz do workspace configurado."""
    if override_dir:
        root = Path(override_dir).resolve()
    else:
        config = storage.load_config()
        root = Path(config.workspace_dir).resolve() if config.workspace_dir else Path(tempfile.gettempdir()) / "agentoffice_workspace"
    
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_and_validate_path(relative_path: str, workspace_dir: Optional[str] = None) -> Path:
    """
    Resolve e valida rigorosamente que o caminho está contido no workspace sandbox.
    Rejeita tentativas de path traversal (..), caminhos absolutos externos e symlinks.
    """
    if not relative_path or not isinstance(relative_path, str):
        raise SecuritySandboxError("Caminho de arquivo inválido ou vazio.")

    ws_root = _get_workspace_dir(workspace_dir)

    # Limpeza de barras iniciais e espaços
    clean_path = relative_path.strip().lstrip("/\\")
    
    # Se o caminho for vazio após strip, aponta para a raiz
    if not clean_path or clean_path == ".":
        target = ws_root
    else:
        target = (ws_root / clean_path).resolve()

    # 1. Barreira estrita contra Path Traversal: target DEVE ter ws_root como ancestral
    try:
        target.relative_to(ws_root)
    except ValueError:
        raise SecuritySandboxError(
            f"Access Denied: Path '{relative_path}' outside workspace sandbox ({ws_root})."
        )

    # 2. Bloqueio estrito de links simbólicos existentes no caminho
    curr = target
    while curr != ws_root and curr != curr.parent:
        if curr.is_symlink():
            raise SecuritySandboxError(
                f"Access Denied: Symlinks are strictly prohibited in workspace sandbox: '{curr}'."
            )
        curr = curr.parent

    if ws_root.is_symlink():
        raise SecuritySandboxError(
            f"Access Denied: Workspace root cannot be a symlink: '{ws_root}'."
        )

    return target


async def fs_list_directory(
    path: str = ".",
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Lista arquivos e subpastas dentro do workspace sandbox com tamanhos e metadados.
    """
    def _sync_list():
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return f"Erro: O diretório '{path}' não existe no workspace."
        if not target.is_dir():
            return f"Erro: O caminho '{path}' não é um diretório."

        ws_root = _get_workspace_dir(workspace_dir)
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        
        rel_dir = str(target.relative_to(ws_root))
        if rel_dir == ".":
            rel_dir = "/"

        lines = [f"📂 Conteúdo de '{rel_dir}' ({len(entries)} itens):"]
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    lines.append(f"  📁 {entry.name}/")
                else:
                    size_bytes = entry.stat().st_size
                    if size_bytes < 1024:
                        size_str = f"{size_bytes} B"
                    elif size_bytes < 1024 * 1024:
                        size_str = f"{size_bytes / 1024:.1f} KB"
                    else:
                        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                    lines.append(f"  📄 {entry.name} ({size_str})")
            except Exception as e:
                lines.append(f"  ⚠️ {entry.name} (erro ao ler: {e})")

        return "\n".join(lines)

    result = await asyncio.to_thread(_sync_list)
    
    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "list_dir", path)

    return result


async def fs_create_directory(
    path: str,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Cria pastas e subpastas de forma recursiva (mkdir -p) dentro do sandbox.
    """
    def _sync_mkdir():
        target = resolve_and_validate_path(path, workspace_dir)
        target.mkdir(parents=True, exist_ok=True)
        ws_root = _get_workspace_dir(workspace_dir)
        return str(target.relative_to(ws_root))

    rel_created = await asyncio.to_thread(_sync_mkdir)
    
    # Notificação WebSocket e atividade visual
    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "created_dir", rel_created)
        await hub.broadcast_system_notice(f"📁 Pasta criada no workspace: '{rel_created}'")

    return f"Diretório '{rel_created}' criado com sucesso."


async def fs_read_file(
    path: str,
    max_lines: int = 500,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Lê o conteúdo de um arquivo de texto com proteção contra binários e limites de tamanho.
    """
    def _sync_read():
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return f"Erro: Arquivo '{path}' não encontrado no workspace."
        if not target.is_file():
            return f"Erro: O caminho '{path}' não é um arquivo regular."

        # Proteção contra binários (lê primeiros 2048 bytes procurando null bytes)
        with open(target, "rb") as f:
            chunk = f.read(2048)
            if b"\x00" in chunk:
                return f"Erro: O arquivo '{path}' parece ser binário e não pode ser lido como texto."

        # Leitura com limite de linhas e tamanho seguro
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"\n... [Leitura truncada após {max_lines} linhas. Use parâmetros específicos se necessário]")
                    break
                lines.append(line)
            
            return "".join(lines)

    result = await asyncio.to_thread(_sync_read)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "read_file", path)

    return result


async def fs_write_file(
    path: str,
    content: str,
    mode: str = "overwrite",
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Cria ou substitui arquivos de texto de forma atômica dentro do workspace sandbox.
    Garante que arquivos parciais não sejam deixados em caso de falha de gravação.
    """
    def _sync_write():
        target = resolve_and_validate_path(path, workspace_dir)
        target.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append" and target.exists():
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            # Escrita atômica: grava em arquivo temporário na mesma pasta e move
            temp_file = target.with_suffix(target.suffix + f".tmp_{os.getpid()}_{id(content)}")
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(temp_file, target)
            finally:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass

        ws_root = _get_workspace_dir(workspace_dir)
        rel_path = str(target.relative_to(ws_root))
        total_lines = len(content.splitlines())
        total_bytes = len(content.encode("utf-8"))
        return rel_path, total_lines, total_bytes

    rel_path, lines_count, bytes_count = await asyncio.to_thread(_sync_write)

    # Notificação WebSocket e atividade visual
    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "created_file", rel_path)
        await hub.broadcast_system_notice(
            f"💾 Arquivo gravado no workspace: '{rel_path}' ({lines_count} linhas, {bytes_count} bytes)"
        )

    return f"Arquivo '{rel_path}' gravado com sucesso ({lines_count} linhas, {bytes_count} bytes)."
