from __future__ import annotations

from datetime import datetime
from typing import Any

from .node_config_service import node_config_service
from .node_state_machine import parse_node_state


REQUEST_HISTORY_LIMIT = 20


def record_node_request_completion(
    config_path: str,
    *,
    request_id: str,
    role: str,
    message: str,
    state: str = "idle",
) -> None:
    safe_request_id = str(request_id or "").strip()
    if not safe_request_id:
        return

    def mutate(next_cfg: dict[str, Any]) -> None:
        record = {
            "request_id": safe_request_id,
            "trace_id": safe_request_id,
            "role": str(role or "assistant").strip().lower() or "assistant",
            "message": str(message or ""),
            "state": parse_node_state(state),
            "node_event_seq": int(next_cfg.get("node_event_seq") or 0),
            "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        }
        existing = next_cfg.get("completed_requests")
        history = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
        history = [item for item in history if str(item.get("request_id") or "") != safe_request_id]
        history.append(record)
        next_cfg["completed_requests"] = history[-REQUEST_HISTORY_LIMIT:]
        next_cfg["last_completed_request"] = record

    node_config_service.update(config_path, mutate, effective="immediate")


def record_node_request_completion_or_log(
    config_path: str,
    *,
    request_id: str,
    role: str,
    message: str,
    state: str = "idle",
    log_error,
    graph_id: str,
    node_id: str,
    node_type_id: str,
    depth: int,
) -> None:
    try:
        record_node_request_completion(
            config_path,
            request_id=request_id,
            role=role,
            message=message,
            state=state,
        )
    except Exception as exc:
        log_error(
            graph_id,
            "node_request_completion_record_error",
            trace_id=request_id,
            node_instance_id=node_id,
            node_type_id=node_type_id,
            depth=depth,
            error=f"{type(exc).__name__}: {exc}",
            message_preview=str(message or "")[:260],
        )


def find_completed_request(payload: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    safe_request_id = str(request_id or "").strip()
    if not safe_request_id or not isinstance(payload, dict):
        return None
    for item in reversed(_completed_requests(payload)):
        if str(item.get("request_id") or "") == safe_request_id:
            return dict(item)
    return None


def _completed_requests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    history = payload.get("completed_requests")
    output: list[dict[str, Any]] = []
    if isinstance(history, list):
        output.extend(item for item in history if isinstance(item, dict))
    last = payload.get("last_completed_request")
    if isinstance(last, dict):
        last_id = str(last.get("request_id") or "")
        if last_id and not any(str(item.get("request_id") or "") == last_id for item in output):
            output.append(last)
    return output


__all__ = [
    "find_completed_request",
    "record_node_request_completion",
    "record_node_request_completion_or_log",
]
