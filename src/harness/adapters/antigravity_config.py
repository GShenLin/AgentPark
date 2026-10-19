"""Native Antigravity selection and node-owned conversation state."""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re

from src.harness.contracts import HarnessContext
from src.harness.session_state import resolve_state_directory
from src.web_backend.node_config_service import read_node_config_optional

DEFAULT_MODEL = "gemini-3.8-flash-medium"


@dataclass(frozen=True)
class AntigravityRequest:
    model: str
    mode: str
    effort: str
    cwd: str
    instruction: str
    timeout: float
    state_dir: Path
    cancel_source: object


def load_request(context: HarnessContext) -> AntigravityRequest:
    if context.values.get("access_role") == "nondeveloper":
        raise ValueError("Antigravity exposes native host tools; developer access is required.")
    config = read_node_config_optional(context.config_path) if os.path.isfile(context.config_path) else {}
    values = {**context.values, **config}
    fields = {key: values.get(key, default) for key, default in (
        ("native_model", DEFAULT_MODEL), ("native_mode", ""), ("native_effort", ""),
        ("working_path", ""), ("instruction", ""))}
    if any(not isinstance(value, str) for value in fields.values()):
        raise ValueError("Antigravity model, mode, effort, working path and instruction must be strings.")
    model, mode, effort = (fields[key].strip() for key in ("native_model", "native_mode", "native_effort"))
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", model) is None:
        raise ValueError("Antigravity native_model must be an explicit model identifier from agy models.")
    if mode not in {"", "plan", "accept-edits"}:
        raise ValueError("Antigravity native_mode must be empty, plan or accept-edits.")
    if effort not in {"", "low", "medium", "high", "xhigh", "max"}:
        raise ValueError("Invalid Antigravity native_effort.")
    timeout = values.get("timeout_seconds", 900)
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 1 <= timeout <= 86400:
        raise ValueError("Antigravity timeout_seconds must be between 1 and 86400.")
    root = Path(context.node_directory).resolve() / ".harness" / "antigravity"
    root.mkdir(parents=True, exist_ok=True)
    raw_cwd = fields["working_path"].strip()
    if raw_cwd:
        cwd = Path(os.path.expanduser(raw_cwd)).resolve()
        if not cwd.is_dir():
            raise ValueError(f"Antigravity working_path does not exist: {cwd}")
    else:
        cwd = root / "workspace"
        cwd.mkdir(exist_ok=True)
    state = resolve_state_directory(root, previous_binding=[model, str(cwd)])
    return AntigravityRequest(model, mode, effort, str(cwd), fields["instruction"], float(timeout), state,
                              context.values.get("cancel_event") or context.values.get("cancel_check"))
