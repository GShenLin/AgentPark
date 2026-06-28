from __future__ import annotations

import ctypes
import os
import sys


RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
MAGENTA = "\x1b[35m"
BLUE = "\x1b[34m"

ROLE_STYLES = {
    "assistant": GREEN,
    "error": RED,
    "help": CYAN,
    "status": BLUE,
    "terminal": MAGENTA,
    "tool": YELLOW,
    "user": CYAN,
}

STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

_WINDOWS_VT_CACHE: dict[int, bool] = {}


def color_enabled(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("AITOOLS_COLOR", "").lower() in {"0", "false", "no"}:
        return False
    if os.environ.get("AITOOLS_COLOR", "").lower() in {"1", "true", "yes", "always"}:
        return True
    target = stream or sys.stdout
    if not bool(getattr(target, "isatty", lambda: False)()):
        return False
    return _terminal_accepts_ansi(target)


def _terminal_accepts_ansi(stream) -> bool:
    if os.name != "nt":
        return True
    return _enable_windows_virtual_terminal(stream)


def _enable_windows_virtual_terminal(stream) -> bool:
    cache_key = STD_ERROR_HANDLE if stream is sys.stderr else STD_OUTPUT_HANDLE
    cached = _WINDOWS_VT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(cache_key)
        if handle in (0, -1):
            _WINDOWS_VT_CACHE[cache_key] = False
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            _WINDOWS_VT_CACHE[cache_key] = False
            return False
        next_mode = int(mode.value) | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if next_mode != int(mode.value) and not kernel32.SetConsoleMode(handle, next_mode):
            _WINDOWS_VT_CACHE[cache_key] = False
            return False
        _WINDOWS_VT_CACHE[cache_key] = True
        return True
    except Exception:
        _WINDOWS_VT_CACHE[cache_key] = False
        return False


def style(text: object, *codes: str, stream=None) -> str:
    value = str(text)
    if not codes or not color_enabled(stream):
        return value
    return "".join(codes) + value + RESET


def role_label(role: str, *, stream=None) -> str:
    role_text = str(role or "").strip() or "message"
    color = ROLE_STYLES.get(role_text.lower(), BOLD)
    return style(role_text, color, BOLD, stream=stream)


def muted(text: object, *, stream=None) -> str:
    return style(text, DIM, stream=stream)


def accent(text: object, *, stream=None) -> str:
    return style(text, CYAN, BOLD, stream=stream)


def error(text: object, *, stream=None) -> str:
    return style(text, RED, BOLD, stream=stream)


def field_line(key: object, value: object, *, stream=None) -> str:
    return f"  {style(str(key), DIM, stream=stream)}: {value}"
