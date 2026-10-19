"""Native OpenCode configuration; no AgentPark Provider or credential gateway."""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path

from src.harness.contracts import HarnessContext
from src.harness.session_state import resolve_state_directory
from src.web_backend.node_config_service import read_node_config_optional

DEFAULT_MODEL = "opencode/deepseek-v4.1-flash-free"


@dataclass(frozen=True)
class OpenCodeRequest:
    model: str
    mode: str
    effort: str
    cwd: str
    instruction: str
    timeout: float
    state_dir: Path
    cancel_source: object


def load_request(context: HarnessContext) -> OpenCodeRequest:
    if context.values.get("access_role") == "nondeveloper":
        raise ValueError("OpenCode exposes native host tools; developer access is required.")
    config = read_node_config_optional(context.config_path) if os.path.isfile(context.config_path) else {}
    values = {**context.values, **config}
    fields = {key: values.get(key, default) for key, default in (
        ("native_model", DEFAULT_MODEL), ("native_agent", "build"), ("native_effort", ""),
        ("working_path", ""), ("instruction", ""))}
    if any(not isinstance(value, str) for value in fields.values()):
        raise ValueError("OpenCode model, agent, effort, working path and instruction must be strings.")
    model = fields["native_model"].strip()
    if "/" not in model or any(not part for part in model.split("/")) or any(c.isspace() for c in model):
        raise ValueError("OpenCode native_model must be an explicit provider/model identifier.")
    mode = fields["native_agent"].strip()
    if not mode:
        raise ValueError("OpenCode native_agent is required.")
    timeout = values.get("timeout_seconds", 900)
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 1 <= timeout <= 86400:
        raise ValueError("OpenCode timeout_seconds must be between 1 and 86400.")
    root = Path(context.node_directory).resolve() / ".harness" / "opencode"
    root.mkdir(parents=True, exist_ok=True)
    raw_cwd = fields["working_path"].strip()
    if raw_cwd:
        cwd = Path(os.path.expanduser(raw_cwd)).resolve()
        if not cwd.is_dir():
            raise ValueError(f"OpenCode working_path does not exist: {cwd}")
    else:
        cwd = root / "workspace"
        cwd.mkdir(exist_ok=True)
    state = resolve_state_directory(root, previous_binding=[model, str(cwd)])
    return OpenCodeRequest(model, mode, fields["native_effort"].strip(), str(cwd), fields["instruction"],
                           float(timeout), state, context.values.get("cancel_event") or context.values.get("cancel_check"))


def select_option(control: dict, config_id: str, value: str) -> str:
    configs = control.get("configOptions")
    if not isinstance(configs, list):
        raise ValueError("OpenCode did not advertise ACP configOptions.")
    matches = [item for item in configs if isinstance(item, dict) and item.get("id") == config_id]
    if len(matches) != 1 or matches[0].get("type") != "select":
        raise ValueError(f"OpenCode did not advertise one selectable {config_id} option.")
    options = matches[0].get("options")
    if not isinstance(options, list):
        raise ValueError(f"OpenCode {config_id} options must be an array.")
    values = []
    for item in options:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid OpenCode {config_id} option.")
        if "group" in item:
            group = item.get("options")
            if not isinstance(group, list) or any(not isinstance(child, dict) for child in group):
                raise ValueError(f"Invalid OpenCode {config_id} option group.")
            values.extend(child.get("value") for child in group)
        else:
            values.append(item.get("value"))
    if values.count(value) != 1:
        raise ValueError(f"OpenCode {config_id} is unavailable: {value}. Check OpenCode's model catalog and login in Settings → Harness.")
    return value
