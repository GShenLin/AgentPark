"""Execution permissions for Antigravity; model routing belongs to AgentPark."""
from __future__ import annotations

from dataclasses import dataclass
import os
from src.web_backend.node_config_service import read_node_config_optional

# Antigravity 1.4 uses its model catalog entry to enable tool schemas. Custom
# placeholder entries omit all tools. This is a CLI capability profile only:
# the gateway binds every request (including titles) to the node's actual model.
RUNTIME_MODEL = "gemini-3.8-flash-medium"


@dataclass(frozen=True)
class ExecutionOptions:
    mode: str
    auto_approve: bool


def execution_options(context) -> ExecutionOptions:
    config = read_node_config_optional(context.config_path) if os.path.isfile(context.config_path) else {}
    values = {**context.values, **config}
    mode = values.get("native_mode", "")
    if mode not in {"", "plan", "accept-edits"}:
        raise ValueError("Antigravity native_mode must be empty, plan or accept-edits.")
    approve = values.get("native_auto_approve", False)
    if not isinstance(approve, bool):
        raise ValueError("Antigravity native_auto_approve must be a boolean.")
    return ExecutionOptions(mode, approve)
