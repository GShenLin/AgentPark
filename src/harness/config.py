from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path

from src.web_backend.node_config_service import read_node_config_optional
from .contracts import HarnessContext
from .provider_binding import ProviderBinding
from .session_state import resolve_state_directory


CLI_DEFAULTS = {"provider_id": "", "model": "", "instruction": "", "timeout_seconds": 900}
CLI_SCHEMA = {
    "provider_id": {"type": "select", "label": "provider_id", "options": []},
    "model": {"type": "select", "label": "model", "options": []},
    "instruction": {"type": "text", "label": "instruction"},
    "timeout_seconds": {"type": "number", "label": "Timeout (seconds)", "min": 1, "max": 86400},
}
REASONING_SCHEMA = {"type": "select", "label": "推理强度", "options": [],
                    "description": "选择当前 Provider 支持的推理强度；留空使用运行时默认值。"}


@dataclass(frozen=True)
class CliRunRequest:
    binding: ProviderBinding
    cwd: str
    instruction: str
    timeout: float
    state_dir: Path
    cancel_source: object
    reasoning_effort: str = ""


def load_cli_request(harness_id: str, context: HarnessContext) -> CliRunRequest:
    # CLI/SDK runtimes expose host tools without AgentPark's sandbox contract.
    if context.values.get("access_role") == "nondeveloper":
        raise ValueError(f"{harness_id} does not provide an enforced read-only sandbox; developer access is required.")
    config = read_node_config_optional(context.config_path) if os.path.isfile(context.config_path) else {}
    if not isinstance(config, dict):
        raise ValueError("Harness node config must be a JSON object.")
    values = {**context.values, **config}
    provider = values.get("provider_id", "")
    model = values.get("model", "")
    if not isinstance(provider, str) or not provider.strip() or not isinstance(model, str):
        raise ValueError("Harness provider_id and model must be strings; provider_id is required.")
    binding = ProviderBinding.resolve(provider.strip(), model.strip())
    reasoning_effort = ""
    if harness_id in {"hermes_agent", "openclaw"}:
        from .reasoning_config import validate_reasoning_effort
        reasoning_effort = validate_reasoning_effort(values.get("reasoning_effort", ""), binding.request_config())
    raw_cwd = values.get("working_path", "")
    instruction = values.get("instruction", "")
    if not isinstance(raw_cwd, str) or not isinstance(instruction, str):
        raise ValueError("Harness working_path and instruction must be strings.")
    timeout = values.get("timeout_seconds", 900)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 86400:
        raise ValueError("Harness timeout_seconds must be between 1 and 86400.")
    harness_dir = Path(context.node_directory).resolve() / ".harness" / harness_id
    if raw_cwd.strip():
        cwd = os.path.abspath(os.path.expanduser(raw_cwd))
        if not os.path.isdir(cwd):
            raise ValueError(f"Harness working_path does not exist: {cwd}")
    else:
        # Native runtimes discover instructions and skills from their workspace.
        # The host application's source tree is never an implicit workspace.
        workspace = harness_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        cwd = str(workspace)
    state_dir = resolve_state_directory(
        harness_dir, previous_binding=[binding.provider_id, binding.model_id, cwd, instruction])
    return CliRunRequest(binding, cwd, instruction, float(timeout), state_dir,
                         context.values.get("cancel_event") or context.values.get("cancel_check"), reasoning_effort)
