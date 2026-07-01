from __future__ import annotations

import subprocess
from queue import Queue
from threading import Lock
from typing import Any


_ACTIVE_INTERACTIVE_PROCS: dict[str, dict[str, Any]] = {}
_ACTIVE_PROCS_LOCK = Lock()


def register_console_interactive_proc(
    session_id: str,
    *,
    proc: subprocess.Popen,
    input_queue: Queue,
    encoding: str,
    graph_id: str = "",
    node_id: str = "",
) -> None:
    safe_session_id = str(session_id or "").strip()
    if not safe_session_id:
        return
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_INTERACTIVE_PROCS[safe_session_id] = {
            "proc": proc,
            "encoding": str(encoding or ""),
            "input_queue": input_queue,
            "graph_id": str(graph_id or ""),
            "node_id": str(node_id or ""),
        }


def unregister_console_interactive_proc(session_id: str) -> None:
    safe_session_id = str(session_id or "").strip()
    if not safe_session_id:
        return
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_INTERACTIVE_PROCS.pop(safe_session_id, None)


def send_console_interactive_input(
    session_id: str,
    text: str,
    *,
    send_eof: bool = False,
    send_ctrl_c: bool = False,
    append_newline: bool = False,
) -> bool:
    safe_session_id = str(session_id or "").strip()
    if not safe_session_id:
        return False
    with _ACTIVE_PROCS_LOCK:
        entry = _ACTIVE_INTERACTIVE_PROCS.get(safe_session_id)
    if not entry:
        return False
    proc = entry.get("proc")
    input_queue = entry.get("input_queue")
    if not callable(getattr(proc, "poll", None)):
        return False
    if proc.poll() is not None or not isinstance(input_queue, Queue):
        return False
    try:
        send_text = str(text or "")
        if append_newline and not send_text.endswith("\n"):
            send_text += "\n"
        input_queue.put(
            {
                "text": send_text,
                "send_eof": bool(send_eof),
                "send_ctrl_c": bool(send_ctrl_c),
            }
        )
        return True
    except Exception:
        return False
