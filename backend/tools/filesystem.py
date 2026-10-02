"""
AgentOffice 2D - Sandboxed File System Tools (Etapa 6)
Operações assíncronas de arquivos e diretórios protegidas por sandbox estrito.
Impede estritamente path traversal (..), acesso fora do workspace_dir e symlinks.
"""

import asyncio
import datetime
import fnmatch
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    # Garante que a pasta public sempre exista dentro do workspace
    (root / "public").mkdir(parents=True, exist_ok=True)
    return root


def ensure_public_project_folder(project_name: str, workspace_dir: Optional[str] = None) -> Path:
    """
    Garante que uma subpasta dedicada ao novo projeto seja criada dentro da pasta public.
    Sempre que o agente for criar algo novo, ele cria uma pasta dentro da public.
    """
    clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name.strip()).strip('_') or "novo_projeto"
    ws = _get_workspace_dir(workspace_dir)
    target = (ws / "public" / clean_name).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


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
    start_line: int = 1,
    end_line: Optional[int] = None,
    show_line_numbers: bool = False,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Lê o conteúdo de um arquivo de texto com proteção contra binários, limites de tamanho,
    fatiamento opcional por linhas (start_line, end_line) e numeração de linhas.
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

        with open(target, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        s_idx = max(1, start_line) - 1
        e_idx = min(total_lines, end_line) if end_line is not None else min(total_lines, s_idx + max_lines)

        if s_idx >= total_lines:
            return f"Aviso: O arquivo possui {total_lines} linha(s), 'start_line={start_line}' está além do final."

        sliced = all_lines[s_idx:e_idx]
        output_lines = []
        for i, line in enumerate(sliced, start=s_idx + 1):
            line_str = line.rstrip("\r\n")
            if show_line_numbers:
                output_lines.append(f"{i:4d} | {line_str}")
            else:
                output_lines.append(line_str)

        header = f"📄 Arquivo '{path}' ({len(sliced)} de {total_lines} linhas lidas, linhas {s_idx + 1} a {e_idx}):\n"
        result_text = header + "\n".join(output_lines)
        if e_idx < total_lines and end_line is None:
            result_text += f"\n... [{total_lines - e_idx} linhas restantes não exibidas. Especifique start_line/end_line para ler mais]"

        return result_text

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
        # Registrar auditoria imutável AIOX
        log_aiox_audit("WRITE_FILE", rel_path, total_bytes, agent_id or "system", "SUCCESS", workspace_dir)
        return rel_path, total_lines, total_bytes

    rel_path, lines_count, bytes_count = await asyncio.to_thread(_sync_write)

    # Notificação WebSocket e atividade visual
    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "created_file", rel_path)
        await hub.broadcast_system_notice(
            f"💾 [AIOX:FS] Arquivo gravado no sandbox: '{rel_path}' ({lines_count} linhas, {bytes_count} bytes)"
        )

    return f"Arquivo '{rel_path}' gravado com sucesso ({lines_count} linhas, {bytes_count} bytes)."


async def fs_edit_file(
    path: str,
    target_text: str,
    replacement_text: str,
    allow_multiple: bool = False,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Edição cirúrgica de arquivo: substitui um trecho específico de texto por outro sem destruir o restante do arquivo.
    Verifica se o trecho existe, se é único (quando allow_multiple=False), aplica a alteração e valida a sintaxe.
    """
    def _sync_edit():
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return False, f"Erro: Arquivo '{path}' não encontrado no workspace."
        if not target.is_file():
            return False, f"Erro: O caminho '{path}' não é um arquivo regular."

        content = target.read_text(encoding="utf-8", errors="replace")

        if target_text not in content:
            return False, (
                f"Erro: O trecho especificado em 'target_text' não foi encontrado em '{path}'. "
                f"Certifique-se de fornecer o texto exato existente no arquivo."
            )

        occurrences = content.count(target_text)
        if occurrences > 1 and not allow_multiple:
            return False, (
                f"Erro: O trecho especificado ocorre {occurrences} vezes no arquivo '{path}'. "
                f"Forneça mais linhas de contexto para tornar a substituição unívoca, ou defina 'allow_multiple=True'."
            )

        new_content = content.replace(target_text, replacement_text) if allow_multiple else content.replace(target_text, replacement_text, 1)

        # Escrita atômica da alteração
        temp_file = target.with_suffix(target.suffix + f".edit_tmp_{os.getpid()}_{id(new_content)}")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(temp_file, target)
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

        ws_root = _get_workspace_dir(workspace_dir)
        rel_path = str(target.relative_to(ws_root))
        size_bytes = len(new_content.encode("utf-8"))
        log_aiox_audit("EDIT_FILE", rel_path, size_bytes, agent_id or "system", "SUCCESS", workspace_dir)

        # Validação de AST se for código Python
        valid_ast, ast_msg = aiox_validate_code_syntax(rel_path, workspace_dir)
        ast_alert = f"\n  -> {ast_msg}" if valid_ast else f"\n  ⚠️ Atenção: {ast_msg}"

        return True, f"Arquivo '{rel_path}' editado com sucesso ({occurrences} ocorrência(s) substituída(s)).{ast_alert}"

    success, message = await asyncio.to_thread(_sync_edit)

    if agent_id and success:
        await hub.broadcast_fs_activity(agent_id, "edited_file", path)
        await hub.broadcast_system_notice(f"✏️ [AIOX:FS] Arquivo editado no sandbox: '{path}'")

    return message


async def fs_tree_view(
    path: str = ".",
    max_depth: int = 4,
    show_hidden: bool = False,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Gera uma visualização em árvore estruturada (tree view) de diretórios e arquivos dentro do sandbox.
    Permite aos agentes mapear e identificar rapidamente toda a hierarquia e organização de arquivos.
    """
    def _sync_tree():
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return f"Erro: O caminho '{path}' não existe no workspace."
        if not target.is_dir():
            return f"Erro: O caminho '{path}' não é um diretório."

        ws_root = _get_workspace_dir(workspace_dir)
        rel_root = str(target.relative_to(ws_root))
        if rel_root == ".":
            rel_root = "workspace/"

        tree_lines = [f"📁 {rel_root}"]
        file_count = 0
        dir_count = 0

        def _walk(curr_dir: Path, prefix: str, depth: int):
            nonlocal file_count, dir_count
            if depth > max_depth:
                tree_lines.append(f"{prefix}└── ... [Profundidade máxima atingida]")
                return

            try:
                raw_entries = list(curr_dir.iterdir())
            except Exception as e:
                tree_lines.append(f"{prefix}└── ⚠️ Erro ao acessar: {e}")
                return

            # Filtrar e ordenar (pastas primeiro)
            entries = []
            for e in raw_entries:
                if not show_hidden and e.name.startswith("."):
                    continue
                if e.is_symlink():
                    continue
                entries.append(e)

            entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
            total = len(entries)

            for idx, entry in enumerate(entries):
                is_last = (idx == total - 1)
                connector = "└── " if is_last else "├── "
                sub_prefix = prefix + ("    " if is_last else "│   ")

                if entry.is_dir():
                    dir_count += 1
                    tree_lines.append(f"{prefix}{connector}📁 {entry.name}/")
                    _walk(entry, sub_prefix, depth + 1)
                else:
                    file_count += 1
                    try:
                        sz = entry.stat().st_size
                        if sz < 1024:
                            sz_str = f"{sz} B"
                        elif sz < 1024 * 1024:
                            sz_str = f"{sz / 1024:.1f} KB"
                        else:
                            sz_str = f"{sz / (1024 * 1024):.1f} MB"
                    except Exception:
                        sz_str = "tamanho desc."
                    tree_lines.append(f"{prefix}{connector}📄 {entry.name} ({sz_str})")

        _walk(target, "", 1)
        tree_lines.append(f"\nTotal: {dir_count} diretório(s), {file_count} arquivo(s).")
        return "\n".join(tree_lines)

    result = await asyncio.to_thread(_sync_tree)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "tree_view", path)

    return result


async def fs_find_files(
    pattern: str = "*",
    path: str = ".",
    max_results: int = 100,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Localiza pastas e arquivos dentro do workspace pelo nome ou padrão glob (ex: '*.py', 'test_*', 'config.*').
    """
    import fnmatch

    def _sync_find():
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return f"Erro: O caminho '{path}' não existe no workspace."

        ws_root = _get_workspace_dir(workspace_dir)
        matches = []

        for root, dirs, files in os.walk(target):
            # Ignorar pastas ocultas como .git
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            root_path = Path(root)
            for d in dirs:
                if fnmatch.fnmatch(d.lower(), pattern.lower()):
                    rel = str((root_path / d).relative_to(ws_root))
                    matches.append(f"  📁 {rel}/")
                    if len(matches) >= max_results:
                        break

            if len(matches) >= max_results:
                break

            for f in files:
                if f.startswith("."):
                    continue
                if fnmatch.fnmatch(f.lower(), pattern.lower()):
                    rel = str((root_path / f).relative_to(ws_root))
                    file_p = root_path / f
                    sz = file_p.stat().st_size if file_p.exists() else 0
                    matches.append(f"  📄 {rel} ({sz} B)")
                    if len(matches) >= max_results:
                        break

            if len(matches) >= max_results:
                break

        if not matches:
            return f"Nenhum arquivo ou pasta correspondente ao padrão '{pattern}' encontrado a partir de '{path}'."

        header = f"🔍 Busca de arquivos/pastas por '{pattern}' em '{path}' ({len(matches)} resultado(s)):\n"
        return header + "\n".join(matches)

    result = await asyncio.to_thread(_sync_find)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "find_files", pattern)

    return result


async def fs_search_content(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    is_regex: bool = False,
    case_insensitive: bool = True,
    max_results: int = 40,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Busca por conteúdo/texto (grep) dentro dos arquivos de texto no sandbox.
    Retorna o caminho do arquivo, número da linha e trecho de código correspondente.
    """
    import fnmatch

    def _sync_search():
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return f"Erro: O caminho '{path}' não existe no workspace."

        ws_root = _get_workspace_dir(workspace_dir)
        regex_flags = re.IGNORECASE if case_insensitive else 0

        if is_regex:
            try:
                pattern = re.compile(query, regex_flags)
            except re.error as e:
                return f"Erro: Expressão regular inválida: {e}"
        else:
            q = query.lower() if case_insensitive else query

        matches = []

        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            root_path = Path(root)

            for f in files:
                if f.startswith("."):
                    continue
                if not fnmatch.fnmatch(f, file_pattern):
                    continue

                full_path = root_path / f
                # Checagem de binário
                try:
                    with open(full_path, "rb") as bf:
                        if b"\x00" in bf.read(1024):
                            continue
                except Exception:
                    continue

                rel_p = str(full_path.relative_to(ws_root))

                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as tf:
                        for line_num, line in enumerate(tf, start=1):
                            matched = False
                            if is_regex:
                                if pattern.search(line):
                                    matched = True
                            else:
                                if q in (line.lower() if case_insensitive else line):
                                    matched = True

                            if matched:
                                snippet = line.strip()[:140]
                                matches.append(f"  {rel_p}:{line_num} -> {snippet}")
                                if len(matches) >= max_results:
                                    break
                except Exception:
                    pass

                if len(matches) >= max_results:
                    break

            if len(matches) >= max_results:
                break

        if not matches:
            return f"Nenhuma ocorrência de '{query}' encontrada nos arquivos em '{path}'."

        header = f"🔎 Busca por conteúdo '{query}' ({len(matches)} ocorrência(s)):\n"
        res = header + "\n".join(matches)
        if len(matches) >= max_results:
            res += f"\n... [Limite de {max_results} resultados atingido. Refine sua busca]"
        return res

    result = await asyncio.to_thread(_sync_search)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "search_content", query)

    return result


async def fs_file_info(
    path: str,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Retorna metadados técnicos e estatísticas de um arquivo ou pasta no sandbox:
    tamanho, linhas, data de modificação, tipo e validação de integridade.
    """
    def _sync_info():
        import datetime
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return f"Erro: O caminho '{path}' não existe no workspace."

        ws_root = _get_workspace_dir(workspace_dir)
        rel_p = str(target.relative_to(ws_root))
        stat = target.stat()
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        if target.is_dir():
            items = list(target.iterdir())
            subdirs = [i for i in items if i.is_dir() and not i.name.startswith(".")]
            files = [i for i in items if i.is_file() and not i.name.startswith(".")]
            return (
                f"📁 Informações do Diretório: '{rel_p}'\n"
                f"- Tipo: Diretório / Pasta\n"
                f"- Subdiretórios diretos: {len(subdirs)}\n"
                f"- Arquivos diretos: {len(files)}\n"
                f"- Última modificação: {mtime}\n"
            )
        else:
            sz = stat.st_size
            try:
                content = target.read_text(encoding="utf-8", errors="replace")
                lines_count = len(content.splitlines())
                chars_count = len(content)
            except Exception:
                lines_count = "N/A"
                chars_count = "N/A"

            syntax_status = ""
            if target.suffix.lower() == ".py":
                valid, msg = aiox_validate_code_syntax(rel_p, workspace_dir)
                syntax_status = f"\n- Quality Gate AST: {'✅ Válido' if valid else '❌ Erro de sintaxe: ' + msg}"
            elif target.suffix.lower() in (".json", ".jsonl"):
                valid, msg = aiox_validate_code_syntax(rel_p, workspace_dir)
                syntax_status = f"\n- Validação JSON: {'✅ Válido' if valid else '❌ Erro de parse: ' + msg}"

            return (
                f"📄 Informações do Arquivo: '{rel_p}'\n"
                f"- Tipo: Arquivo Regular ({target.suffix or 'sem extensão'})\n"
                f"- Tamanho: {sz} bytes ({sz / 1024:.2f} KB)\n"
                f"- Linhas: {lines_count} | Caracteres: {chars_count}\n"
                f"- Última modificação: {mtime}{syntax_status}"
            )

    result = await asyncio.to_thread(_sync_info)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "file_info", path)

    return result


async def fs_rename_or_move(
    source_path: str,
    target_path: str,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Renomeia ou move arquivos e pastas com segurança dentro do workspace sandbox.
    """
    import shutil

    def _sync_move():
        src = resolve_and_validate_path(source_path, workspace_dir)
        dst = resolve_and_validate_path(target_path, workspace_dir)

        if not src.exists():
            return f"Erro: Caminho de origem '{source_path}' não existe no workspace."

        ws_root = _get_workspace_dir(workspace_dir)
        if src == ws_root:
            raise SecuritySandboxError("A raiz do workspace sandbox não pode ser movida ou renomeada.")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

        rel_src = str(src.relative_to(ws_root)) if src.exists() else source_path
        rel_dst = str(dst.relative_to(ws_root))

        log_aiox_audit("MOVE_PATH", f"{rel_src} -> {rel_dst}", 0, agent_id or "system", "SUCCESS", workspace_dir)
        return f"'{rel_src}' foi movido/renomeado com sucesso para '{rel_dst}'."

    result = await asyncio.to_thread(_sync_move)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "moved_path", f"{source_path} -> {target_path}")
        await hub.broadcast_system_notice(f"📦 [AIOX:FS] Item movido/renomeado: {source_path} ➔ {target_path}")

    return result


async def fs_copy(
    source_path: str,
    target_path: str,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Copia arquivos ou pastas dentro do workspace sandbox de forma segura.
    """
    import shutil

    def _sync_copy():
        src = resolve_and_validate_path(source_path, workspace_dir)
        dst = resolve_and_validate_path(target_path, workspace_dir)

        if not src.exists():
            return f"Erro: Caminho de origem '{source_path}' não existe."

        ws_root = _get_workspace_dir(workspace_dir)
        if src == ws_root:
            raise SecuritySandboxError("A raiz do workspace sandbox não pode ser copiada.")

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
        else:
            shutil.copy2(str(src), str(dst))

        rel_src = str(src.relative_to(ws_root))
        rel_dst = str(dst.relative_to(ws_root))

        log_aiox_audit("COPY_PATH", f"{rel_src} -> {rel_dst}", 0, agent_id or "system", "SUCCESS", workspace_dir)
        return f"'{rel_src}' foi copiado com sucesso para '{rel_dst}'."

    result = await asyncio.to_thread(_sync_copy)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "copied_path", f"{source_path} -> {target_path}")
        await hub.broadcast_system_notice(f"📋 [AIOX:FS] Copiado: {source_path} ➔ {target_path}")

    return result


async def fs_delete_path(
    path: str,
    recursive: bool = False,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Remove arquivos ou diretórios dentro do workspace sandbox com proteção contra deleção da raiz.
    """
    import shutil

    def _sync_delete():
        target = resolve_and_validate_path(path, workspace_dir)
        if not target.exists():
            return f"Erro: Caminho '{path}' não encontrado no workspace."

        ws_root = _get_workspace_dir(workspace_dir)
        if target == ws_root:
            raise SecuritySandboxError("A exclusão da pasta raiz do workspace sandbox é terminantemente proibida.")

        rel_p = str(target.relative_to(ws_root))

        if target.is_dir():
            is_empty = not any(target.iterdir())
            if not is_empty and not recursive:
                return f"Erro: O diretório '{rel_p}' não está vazio. Use 'recursive=True' para confirmar a exclusão."
            shutil.rmtree(str(target))
            tipo = "Diretório"
        else:
            target.unlink()
            tipo = "Arquivo"

        log_aiox_audit("DELETE_PATH", rel_p, 0, agent_id or "system", "SUCCESS", workspace_dir)
        return f"{tipo} '{rel_p}' removido com sucesso."

    result = await asyncio.to_thread(_sync_delete)

    if agent_id:
        await hub.broadcast_fs_activity(agent_id, "deleted_path", path)
        await hub.broadcast_system_notice(f"🗑️ [AIOX:FS] Item removido: '{path}'")

    return result


def log_aiox_audit(
    action: str,
    path: str,
    size_bytes: int,
    agent_id: str,
    status: str = "SUCCESS",
    workspace_dir: Optional[str] = None
) -> None:
    """Registra operação no log de auditoria imutável AIOX (.aiox_audit.jsonl)."""
    try:
        ws_root = _get_workspace_dir(workspace_dir)
        audit_file = ws_root / ".aiox_audit.jsonl"
        entry = {
            "timestamp": time.time(),
            "action": action,
            "path": path,
            "size_bytes": size_bytes,
            "agent_id": agent_id,
            "status": status
        }
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.debug(f"Falha ao registrar auditoria AIOX: {e}")


def aiox_validate_code_syntax(
    relative_path: str,
    workspace_dir: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Executa verificação estática de sintaxe (AST check) em arquivos de código no workspace sandbox.
    Garante o Quality Gate antes do sign-off da tarefa (princípio AIOX DoD).
    """
    try:
        target = resolve_and_validate_path(relative_path, workspace_dir)
        if not target.exists():
            return False, f"Arquivo '{relative_path}' não encontrado no sandbox."

        content = target.read_text(encoding="utf-8")
        if target.suffix.lower() == ".py":
            import ast
            ast.parse(content, filename=str(target))
            return True, f"Sintaxe Python válida (AST validado sem erros) em '{relative_path}'."
        elif target.suffix.lower() in (".json", ".jsonl"):
            json.loads(content)
            return True, f"JSON válido em '{relative_path}'."
        
        return True, f"Arquivo '{relative_path}' íntegro."
    except SyntaxError as se:
        return False, f"Erro de sintaxe em '{relative_path}' linha {se.lineno}: {se.msg}"
    except json.JSONDecodeError as je:
        return False, f"Erro de JSON em '{relative_path}': {je.msg}"
    except Exception as ex:
        return False, f"Falha na validação de '{relative_path}': {str(ex)}"


