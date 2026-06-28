from __future__ import annotations

import os
import sys


TERMINAL_DEBUG_ENV_KEYS = (
    "TERM",
    "WT_SESSION",
    "ConEmuPID",
    "ANSICON",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
)


def build_terminal_debug_text(
    *,
    input_backend: str,
    backend_report: str = "",
    event_backend: str = "",
    all_backends: str = "",
    include_encoding: bool = True,
    include_env: bool = True,
) -> str:
    values = [
        _debug_value("os.name", os.name),
        _debug_value("stdin.isatty", sys.stdin.isatty()),
        _debug_value("stdout.isatty", sys.stdout.isatty()),
        _debug_value("stderr.isatty", sys.stderr.isatty()),
    ]
    if include_encoding:
        values.extend(
            [
                _debug_value("stdin.encoding", getattr(sys.stdin, "encoding", "")),
                _debug_value("stdout.encoding", getattr(sys.stdout, "encoding", "")),
            ]
        )
    values.append(f"input_backend: {input_backend}")
    if event_backend:
        values.append(f"event_backend: {event_backend}")
    if backend_report:
        values.append(f"backend_report: {backend_report}")
    if all_backends:
        values.append(f"all_backends: {all_backends}")
    if include_env:
        values.extend(f"env.{key}: {os.environ.get(key, '')}" for key in TERMINAL_DEBUG_ENV_KEYS)
    return "\n".join(values)


def _debug_value(name: str, value: object) -> str:
    return f"{name}: {value}"
