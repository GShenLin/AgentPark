from __future__ import annotations

import contextlib
import ctypes
import json
import os
from dataclasses import dataclass
from typing import Iterator

from src.file_transaction import atomic_write_text
from src.web_backend import runtime_paths


CLI_WINDOW_STATE_NAME = "agentpark-cli-window.json"
SW_HIDE = 0
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GA_ROOTOWNER = 3
PSEUDO_CONSOLE_WINDOW_CLASS = "PseudoConsoleWindow"
WINDOWS_TERMINAL_WINDOW_CLASS = "CASCADIA_HOSTING_WINDOW_CLASS"


@dataclass(frozen=True)
class CompanionCliWindowStatus:
    running: bool
    visible: bool
    pid: int = 0
    handle: int = 0


def cli_window_state_path() -> str:
    return os.path.join(runtime_paths._get_runtime_root(), ".runtime", CLI_WINDOW_STATE_NAME)


def register_companion_cli_window(*, start_hidden: bool = False) -> CompanionCliWindowStatus:
    if os.name != "nt":
        return CompanionCliWindowStatus(running=True, visible=True, pid=os.getpid())
    handle = _resolve_console_window_handle()
    if handle <= 0:
        raise RuntimeError("Companion CLI is not attached to a Windows console window")
    if start_hidden:
        _show_window(handle, SW_HIDE)
    state = {
        "pid": os.getpid(),
        "handle": str(handle),
        "workspace_root": os.path.abspath(runtime_paths._get_runtime_root()),
    }
    path = cli_window_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return CompanionCliWindowStatus(running=True, visible=_is_window_visible(handle), pid=os.getpid(), handle=handle)


def unregister_companion_cli_window() -> None:
    path = cli_window_state_path()
    state = _read_state(path)
    if state is None or state["pid"] != os.getpid():
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        return


def get_companion_cli_window_status() -> CompanionCliWindowStatus:
    if os.name != "nt":
        return CompanionCliWindowStatus(running=False, visible=False)
    state = _read_state(cli_window_state_path())
    if state is None:
        return CompanionCliWindowStatus(running=False, visible=False)
    pid = state["pid"]
    handle = state["handle"]
    if not _process_alive(pid) or not _is_window(handle):
        return CompanionCliWindowStatus(running=False, visible=False)
    return CompanionCliWindowStatus(
        running=True,
        visible=_is_window_visible(handle),
        pid=pid,
        handle=handle,
    )


def hide_companion_cli_window() -> None:
    status = get_companion_cli_window_status()
    if not status.running:
        raise RuntimeError("Companion CLI window is not running")
    _show_window(status.handle, SW_HIDE)


def show_companion_cli_window() -> None:
    status = get_companion_cli_window_status()
    if not status.running:
        raise RuntimeError("Companion CLI window is not running")
    _show_window(status.handle, SW_RESTORE)


@contextlib.contextmanager
def companion_cli_window_session(*, start_hidden: bool) -> Iterator[CompanionCliWindowStatus]:
    status = register_companion_cli_window(start_hidden=start_hidden)
    try:
        yield status
    finally:
        unregister_companion_cli_window()


def _read_state(path: str) -> dict[str, int] | None:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expected_root = os.path.normcase(os.path.abspath(runtime_paths._get_runtime_root()))
    payload_root = os.path.normcase(os.path.abspath(str(payload.get("workspace_root") or "")))
    if payload_root != expected_root:
        return None
    try:
        pid = int(payload.get("pid") or 0)
        window_handle = int(payload.get("handle") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 0 or window_handle <= 0:
        return None
    return {"pid": pid, "handle": window_handle}


def _get_console_window() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    return int(kernel32.GetConsoleWindow() or 0)


def _resolve_console_window_handle() -> int:
    console_handle = _get_console_window()
    if console_handle <= 0:
        return 0
    if _get_window_class_name(console_handle) != PSEUDO_CONSOLE_WINDOW_CLASS:
        return console_handle

    terminal_handle = _get_ancestor_window(console_handle, GA_ROOTOWNER)
    if terminal_handle <= 0 or _get_window_class_name(terminal_handle) != WINDOWS_TERMINAL_WINDOW_CLASS:
        raise RuntimeError(
            "Companion CLI is hosted by a pseudoconsole, but its Windows Terminal window could not be resolved"
        )
    return terminal_handle


def _get_ancestor_window(handle: int, relationship: int) -> int:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    user32.GetAncestor.restype = ctypes.c_void_p
    return int(user32.GetAncestor(ctypes.c_void_p(handle), relationship) or 0)


def _get_window_class_name(handle: int) -> str:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    buffer = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(ctypes.c_void_p(handle), buffer, len(buffer))
    if length <= 0:
        error_code = ctypes.get_last_error()
        if error_code:
            raise OSError(error_code, "Unable to read the console window class")
        return ""
    return buffer.value


def _is_window(handle: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_bool
    return bool(user32.IsWindow(ctypes.c_void_p(handle)))


def _is_window_visible(handle: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    return bool(user32.IsWindowVisible(ctypes.c_void_p(handle)))


def _show_window(handle: int, command: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindowAsync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindowAsync.restype = ctypes.c_bool
    user32.ShowWindowAsync(ctypes.c_void_p(handle), command)


def _process_alive(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return False
    kernel32.CloseHandle(process)
    return True


__all__ = [
    "CompanionCliWindowStatus",
    "cli_window_state_path",
    "companion_cli_window_session",
    "get_companion_cli_window_status",
    "hide_companion_cli_window",
    "show_companion_cli_window",
]
