from __future__ import annotations

import copy
import os
from datetime import datetime
from typing import Any


RESTART_RECOVERY_SCHEMA_VERSION = 1
RESTART_RECOVERY_KIND = "agentpark_restart_checkpoint"
RESTART_TAG_KIND = "agentpark_restart_tag"
RESTORED_RUNTIME_FIELDS = (
    "node_event_seq",
    "last_message",
    "last_output_resources",
    "last_run_at",
    "last_runtime_event",
    "runtime_events",
    "runtime_tool_calls",
    "provider_request_summaries",
    "provider_request_totals",
    "completed_requests",
    "last_completed_request",
    "goal",
    "goal_state",
    "held_outputs",
)
_MODEL_STATE_FIELDS = (
    "state",
    "inflight_at",
    "last_message",
    "last_run_at",
    "last_runtime_event",
    "goal",
    "goal_state",
    "pending_count",
)


class RestartRecoveryError(RuntimeError):
    pass


def build_restart_checkpoint(
    *,
    restart_id: str,
    graph_id: str,
    node_id: str,
    type_id: str,
    config_path: str,
    graphs_dir: str,
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    snapshot = copy.deepcopy(runtime_state)
    inflight = snapshot.get("inflight")
    previous_recovery = None
    if isinstance(inflight, dict):
        inflight.pop("_runtime_owner_id", None)
        previous_recovery = inflight.pop("_restart_recovery", None)
    for item in snapshot.get("pending") or []:
        if isinstance(item, dict):
            item.pop("_runtime_owner_id", None)
    return {
        "schema_version": RESTART_RECOVERY_SCHEMA_VERSION,
        "kind": RESTART_RECOVERY_KIND,
        "restart_id": restart_id,
        "graph_id": graph_id,
        "node_id": node_id,
        "node_type_id": type_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="microseconds"),
        "config_relative_path": os.path.relpath(config_path, graphs_dir).replace("\\", "/"),
        "previous_restart_id": str((previous_recovery or {}).get("restart_id") or ""),
        "runtime_state": snapshot,
    }


def build_restart_model_state(checkpoint: dict[str, Any]) -> dict[str, Any]:
    snapshot = checkpoint["runtime_state"]
    inflight = snapshot.get("inflight") if isinstance(snapshot.get("inflight"), dict) else {}
    runtime = {field: copy.deepcopy(snapshot[field]) for field in _MODEL_STATE_FIELDS if field in snapshot}
    return {
        "restart_id": str(checkpoint["restart_id"]),
        "checkpoint_created_at": str(checkpoint["created_at"]),
        "graph_id": str(checkpoint["graph_id"]),
        "node_id": str(checkpoint["node_id"]),
        "node_type_id": str(checkpoint["node_type_id"]),
        "interrupted_task": {
            key: copy.deepcopy(inflight[key])
            for key in ("trace_id", "request_id", "source", "depth", "from")
            if key in inflight
        },
        "runtime_state": runtime,
    }


def validate_restart_checkpoint(checkpoint: dict[str, Any], tag: dict[str, Any]) -> None:
    if checkpoint.get("schema_version") != RESTART_RECOVERY_SCHEMA_VERSION:
        raise RestartRecoveryError("unsupported restart checkpoint schema")
    if checkpoint.get("kind") != RESTART_RECOVERY_KIND:
        raise RestartRecoveryError("invalid restart checkpoint kind")
    for field in ("restart_id", "graph_id", "node_id"):
        if str(checkpoint.get(field) or "") != str(tag.get(field) or ""):
            raise RestartRecoveryError(f"restart checkpoint {field} does not match tag")
    snapshot = checkpoint.get("runtime_state")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("inflight"), dict):
        raise RestartRecoveryError("restart checkpoint has no recoverable inflight item")


__all__ = [
    "RESTART_RECOVERY_SCHEMA_VERSION",
    "RESTART_TAG_KIND",
    "RESTORED_RUNTIME_FIELDS",
    "RestartRecoveryError",
    "build_restart_checkpoint",
    "build_restart_model_state",
    "validate_restart_checkpoint",
]
