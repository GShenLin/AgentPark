from __future__ import annotations

import time
from typing import Any, Callable

from src.message_protocol import envelope_text, normalize_envelope

from .node_state_machine import parse_node_state


EDITABLE_NODE_CONFIG_FIELDS = {
    "allowed_tools",
    "collaboration_mode",
    "mcp_servers",
    "mode",
    "plugins",
    "reasoning_effort",
    "response_format",
    "skills",
    "system_prompt",
    "system_prompt_append",
    "thinking",
    "tools",
    "web_search",
    "working_directory",
    "working_path",
}


def normalize_seq(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def wait_payload(
    started: float,
    timeout: float,
    completed: bool,
    changed: bool,
    *,
    timed_out: bool,
    state: dict[str, Any],
    request_id: str = "",
) -> dict[str, Any]:
    payload = {
        "completed": completed,
        "changed": changed,
        "timeout": timed_out,
        "timeout_seconds": timeout,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
        "final_state": parse_node_state(state.get("state")),
        "node_event_seq": int(state.get("node_event_seq") or 0),
    }
    if request_id:
        payload["request_id"] = request_id
    if timed_out:
        payload["next_action"] = {
            "poll": "Call get_node_last_message with wait_until_idle=true and the returned message_id/node_event_seq.",
            "stop": "Call stop_node if the node appears stuck or the task should be cancelled.",
        }
    return payload


def poll_interval(elapsed_seconds: float) -> float:
    if elapsed_seconds < 2:
        return 0.1
    if elapsed_seconds < 30:
        return 0.5
    return 1.0


def positive_int(value: object, *, field: str, default: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be > 0")
    return min(parsed, maximum)


def non_negative_int(value: object, *, field: str, default: int) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{field} must be >= 0")
    return parsed


def graph_metadata(core: object, graph_id: str, domain_call: Callable[[Callable[[], Any]], Any]) -> dict[str, Any]:
    graph = _read_graph_config_metadata(core, graph_id)
    graph_payload = domain_call(lambda: core.graph_api.get_graph(graph_id))
    api_graph = graph_payload.get("graph") if isinstance(graph_payload, dict) else {}
    if isinstance(api_graph, dict):
        graph = {**api_graph, **graph}
    nodes_payload = domain_call(lambda: core.node_ops.list_node_instance_configs(graph_id=graph_id))
    nodes = nodes_payload.get("nodes") if isinstance(nodes_payload, dict) else []
    states = [parse_node_state(item.get("state")) for item in nodes if isinstance(item, dict)]
    if any(state == "working" for state in states):
        state = "working"
    elif any(state == "stop" for state in states):
        state = "partial_stop"
    else:
        state = "idle"
    return {
        "name": str((graph or {}).get("name") or graph_id),
        "description": str((graph or {}).get("description") or ""),
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "state": state,
    }


def _read_graph_config_metadata(core: object, graph_id: str) -> dict[str, Any]:
    try:
        graph = core.graph_runtime._read_graph_config(graph_id)
    except Exception:
        return {}
    return graph if isinstance(graph, dict) else {}


def stable_self_payload(summary: object, graph_id: str, node: dict[str, Any]) -> dict[str, Any]:
    payload = summary.node_status_payload(graph_id, node)
    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    return {
        "available": True,
        "is_self": True,
        "graph_id": str(payload.get("graph_id") or graph_id),
        "node_id": str(payload.get("node_id") or ""),
        "name": str(payload.get("name") or ""),
        "provider": str(capabilities.get("provider") or ""),
        "model": str(capabilities.get("model") or ""),
        "working_path": str(payload.get("working_path") or ""),
        "can": payload.get("can") or {},
    }


def delegation_message(
    message: object,
    *,
    response_format: dict[str, Any] | str | None,
    working_directory: str,
    allowed_tools: list[str] | None,
    system_prompt_append: str,
) -> dict[str, Any]:
    envelope = normalize_envelope(message, default_role="user")
    constraints: dict[str, Any] = {}
    if response_format not in (None, ""):
        constraints["response_format"] = response_format
    if str(working_directory or "").strip():
        constraints["working_directory"] = str(working_directory).strip()
    if isinstance(allowed_tools, list):
        constraints["allowed_tools"] = [str(item) for item in allowed_tools if str(item or "").strip()]
    if str(system_prompt_append or "").strip():
        constraints["system_prompt_append"] = str(system_prompt_append).strip()
    if constraints:
        parts = envelope.get("parts") if isinstance(envelope.get("parts"), list) else []
        envelope["parts"] = [*parts, {"type": "structured", "data": {"delegation_constraints": constraints}}]
    return envelope


def completed_request_snapshot(current: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current)
    snapshot["request_id"] = str(record.get("request_id") or "")
    snapshot["last_message"] = str(record.get("message") or "")
    snapshot["state"] = parse_node_state(record.get("state"))
    snapshot["message_id"] = str(record.get("node_event_seq") or current.get("message_id") or "")
    snapshot["message_version"] = int(record.get("node_event_seq") or current.get("message_version") or 0)
    snapshot["node_event_seq"] = int(record.get("node_event_seq") or current.get("node_event_seq") or 0)
    snapshot["matched_request"] = record
    snapshot["current_state"] = parse_node_state(current.get("state"))
    snapshot["current_node_event_seq"] = int(current.get("node_event_seq") or 0)
    return snapshot


def page_memory_payload(
    payload: dict[str, Any],
    *,
    max_chars: int,
    start_seq: int,
    offset_chars: int,
) -> dict[str, Any]:
    result = dict(payload)
    messages = result.get("messages")
    if isinstance(messages, list):
        indexed = [
            {"seq": index + 1, "message": item}
            for index, item in enumerate(messages)
            if index + 1 >= max(1, start_seq or 1)
        ]
        result["messages"] = [item["message"] for item in indexed]
        result["page"] = {
            "start_seq": start_seq,
            "offset_chars": offset_chars,
            "returned_messages": len(indexed),
        }
        text = "\n".join(envelope_text(item["message"]) for item in indexed).strip()
    else:
        text = str(result.get("text") or "")
        result["page"] = {"start_seq": start_seq, "offset_chars": offset_chars, "returned_messages": 0}
    sliced = text[offset_chars:] if offset_chars else text
    result["text"] = sliced[:max_chars]
    result["page"]["returned_chars"] = len(result["text"])
    result["page"]["truncated"] = len(sliced) > max_chars
    return result


__all__ = [
    "EDITABLE_NODE_CONFIG_FIELDS",
    "completed_request_snapshot",
    "delegation_message",
    "graph_metadata",
    "non_negative_int",
    "normalize_seq",
    "page_memory_payload",
    "poll_interval",
    "positive_int",
    "stable_self_payload",
    "wait_payload",
]
