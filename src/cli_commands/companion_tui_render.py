from __future__ import annotations

import textwrap
import time
from typing import Any


SPINNER = "|/-\\"


def render_tui_text(
    *,
    target: Any,
    state: Any,
    backend: str,
    started_at: float,
    log_path: str,
    spinner_index: int,
    width: int,
    height: int,
) -> str:
    body_height = max(3, height - 10)
    lines = _header_lines(target, backend, started_at, log_path, width)
    transcript = _transcript_lines(state, width)[-body_height:]
    lines.extend(transcript)
    lines.extend([""] * max(0, body_height - len(transcript)))
    lines.extend(_footer_lines(target, state, spinner_index, width))
    return "\n".join(line[:width].ljust(width) for line in lines[:height])


def _header_lines(target: Any, backend: str, started_at: float, log_path: str, width: int) -> list[str]:
    provider = str(target.config.get("provider_id") or "provider-unset")
    mode = str(target.config.get("mode") or "chat")
    reasoning = str(target.config.get("reasoning_effort") or "")
    thinking = str(target.config.get("thinking") or "")
    elapsed = int(time.monotonic() - started_at)
    return [
        " AITools Companion".ljust(width - 1)[: width - 1],
        f" provider {provider} | mode {mode} | reasoning {reasoning} | thinking {thinking}",
        f" graph {target.graph_id} | backend {backend} | elapsed {elapsed}s | log {log_path or '-'}",
        "-" * width,
    ]


def _transcript_lines(state: Any, width: int) -> list[str]:
    lines: list[str] = []
    for item in state.transcript:
        title = item.role if not item.status else f"{item.role} [{item.status}]"
        lines.append(title)
        text = item.text or ("working..." if item.status == "working" else "")
        for part in text.splitlines() or [""]:
            lines.extend(f"  {line}" for line in textwrap.wrap(part, width=max(20, width - 4)) or [""])
        lines.append("")
    return lines


def _footer_lines(target: Any, state: Any, spinner_index: int, width: int) -> list[str]:
    spinner = SPINNER[spinner_index] if state.running else " "
    draft = state.draft[: state.cursor] + "_" + state.draft[state.cursor :]
    queue_text = f" | queued {len(state.queued)}" if state.queued else ""
    debug = f" | keys {state.key_events_seen}"
    if state.last_key:
        debug += f" last {state.last_key}"
    return [
        "-" * width,
        f" {spinner} {state.status}{queue_text}{debug} | Enter send | Ctrl+C clear/quit | /help",
        f" config {target.config_path}",
        f"> {draft}",
    ]
