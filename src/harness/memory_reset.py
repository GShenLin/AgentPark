"""Reset node-owned runtime memory after the caller has stopped node work.

CLI harness state lives in session directories; workspace files are user work.
Codex/Claude keep native archives outside the node, so only their live session
and node-owned resume selection are reset here.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil

from .file_lock import file_lease


CLI_HARNESSES = ("hermes_agent", "openclaw", "deepseek_harness", "pi")


def clear_harness_memory(node_directory: str, config: dict) -> tuple[str, ...]:
    node = Path(node_directory).resolve()
    cleared: list[str] = []
    for harness_id in CLI_HARNESSES:
        root = node / ".harness" / harness_id
        if not root.exists():
            continue
        _require_owned_path(root, node)
        with file_lease(root / ".session-state.lock", exclusive=True):
            # Clear all managed sessions, including those created before the
            # stable session pointer was introduced, not just the selected one.
            targets = [path for path in root.iterdir()
                       if re.fullmatch(r"[0-9a-f]{24}|[0-9a-f]{32}", path.name)]
            pointer = root / "current-session.json"
            if pointer.exists():
                targets.append(pointer)
            for path in targets:
                _require_owned_path(path, root)
            for path in targets:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                cleared.append(str(path))
    cleared.extend(_clear_managed_session(node, config))
    return tuple(cleared)


def _require_owned_path(path: Path, parent: Path) -> None:
    # Do not follow a junction/symlink into another node or a shared directory.
    if path.resolve() != path.absolute() or not path.resolve().is_relative_to(parent.resolve()):
        raise ValueError(f"Harness memory path is not owned by this node: {path}")


def _clear_managed_session(node: Path, config: dict) -> list[str]:
    node_type = config.get("type_id")
    if node_type == "codex_node":
        from nodes.codex_node.runtime.session_manager import CodexSessionManager
        from nodes.codex_node.runtime.thread_state import THREAD_STATE_FILENAME, session_runtime_key
        manager = CodexSessionManager.instance()
        filename = THREAD_STATE_FILENAME
    elif node_type == "claude_node":
        from nodes.claude_node.runtime.session_manager import ClaudeSessionManager
        from nodes.claude_node.runtime.session_state import SESSION_STATE_FILENAME, session_runtime_key
        manager = ClaudeSessionManager.instance()
        filename = SESSION_STATE_FILENAME
    else:
        return []
    state = node / filename
    _require_owned_path(state, node)
    manager.close_session(session_runtime_key(config.get("graph_id", "default"),
                                              config.get("node_id", node.name), str(state)))
    if state.exists():
        state.unlink()
        return [str(state)]
    return []
