from __future__ import annotations

from typing import Any

from .turn_audit_reader import extract_artifact_paths, read_tool_artifacts


def project_turn_detail(
    turn: Any,
    messages: list[dict[str, Any]],
    tool_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    tool_messages = _tool_messages_by_call(
        messages,
        turn.local_call_ids | turn.server_call_ids,
    )
    local_tools = _local_tool_calls(turn, tool_messages, tool_stats)
    server_tools = _server_tool_calls(turn)
    model_rounds = _model_rounds(turn)
    return {
        "model_rounds": model_rounds,
        "tool_calls": local_tools,
        "server_tool_calls": server_tools,
        "file_changes": _collect_file_changes(local_tools),
        "timeline": _build_timeline(
            turn,
            [
                item
                for item in messages
                if str(item.get("role") or "") in {"user", "assistant"}
            ],
            local_tools,
            server_tools,
            model_rounds,
        ),
    }


def _local_tool_calls(
    turn: Any,
    tool_messages: dict[str, dict[str, Any]],
    tool_stats: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    for record in turn.records:
        if record.get("event") not in {"tool_call_start", "tool_call_end"}:
            continue
        event = record.get("runtime_event")
        if not isinstance(event, dict):
            continue
        call_id = str(event.get("call_id") or "").strip()
        if not call_id:
            continue
        call = calls.setdefault(
            call_id,
            {
                "call_id": call_id,
                "name": str(event.get("name") or "tool").strip() or "tool",
                "provider": str(event.get("provider") or "").strip(),
                "started_at": "",
                "completed_at": "",
                "status": "running",
                "duration_ms": None,
                "arguments": None,
                "result": None,
                "result_preview": "",
                "error": "",
                "artifacts": [],
            },
        )
        if record.get("event") == "tool_call_start":
            call["started_at"] = str(event.get("event_time") or record.get("ts") or "")
            call["arguments"] = event.get("arguments")
        else:
            call["completed_at"] = str(event.get("event_time") or record.get("ts") or "")
            call["status"] = str(event.get("status") or "completed")
            call["duration_ms"] = event.get("duration_ms")
            call["result_preview"] = str(event.get("result_preview") or "")
            call["error"] = str(event.get("error") or "")

    for call_id, call in calls.items():
        part = _first_tool_part(tool_messages.get(call_id, {}))
        stat = tool_stats.get(call_id, {})
        call["name"] = str(stat.get("tool_name") or part.get("name") or call["name"])
        call["arguments"] = stat.get("tool_call_arguments") or part.get("args") or call["arguments"]
        if stat:
            call["result"] = stat.get("result")
            call["result_preview"] = str(stat.get("result_preview") or call["result_preview"])
            call["error"] = str(stat.get("error") or call["error"])
        if call["result"] is None:
            call["result"] = _message_result(part)
        artifact_paths = extract_artifact_paths(
            [call["arguments"], call["result"], call["result_preview"], part]
        )
        call["artifacts"] = read_tool_artifacts(turn.node_dir, artifact_paths)
    return sorted(calls.values(), key=lambda item: str(item.get("started_at") or ""))


def _server_tool_calls(turn: Any) -> list[dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    for record in turn.records:
        if record.get("event") != "server_tool_activity":
            continue
        event = record.get("runtime_event")
        if not isinstance(event, dict):
            continue
        call_id = str(event.get("call_id") or "").strip()
        if not call_id:
            continue
        call = calls.setdefault(
            call_id,
            {
                "call_id": call_id,
                "name": str(event.get("tool_type") or "server_tool"),
                "provider": str(event.get("provider") or ""),
                "started_at": str(record.get("ts") or ""),
                "completed_at": "",
                "status": "in_progress",
                "action": None,
                "sources": [],
            },
        )
        status = str(event.get("status") or "in_progress")
        call["status"] = status
        if status in {"completed", "failed", "error", "cancelled", "timeout"}:
            call["completed_at"] = str(record.get("ts") or "")
        if event.get("action") is not None:
            call["action"] = event.get("action")
        if isinstance(event.get("sources"), list):
            call["sources"] = event["sources"]
    return sorted(calls.values(), key=lambda item: str(item.get("started_at") or ""))


def _model_rounds(turn: Any) -> list[dict[str, Any]]:
    rounds: dict[int, dict[str, Any]] = {}
    for record in turn.records:
        event = record.get("runtime_event")
        if not isinstance(event, dict) or event.get("type") != "runtime_notice":
            continue
        stage = str(event.get("stage") or "")
        if stage not in {"provider_request_summary", "provider_request_completed"}:
            continue
        payload = (
            record.get("provider_request_summary")
            if stage == "provider_request_summary"
            else record.get("provider_request_completion")
        )
        if not isinstance(payload, dict):
            payload = _notice_payload(event)
        request_index = _int_or_none(payload.get("request_index"))
        if request_index is None:
            continue
        item = rounds.setdefault(
            request_index,
            {
                "request_index": request_index,
                "started_at": "",
                "completed_at": "",
                "provider": str(event.get("provider") or turn.provider_id),
                "request": None,
                "response": None,
            },
        )
        if stage == "provider_request_summary":
            item["started_at"] = str(record.get("ts") or "")
            item["request"] = payload
        else:
            item["completed_at"] = str(record.get("ts") or "")
            item["response"] = payload
    return [rounds[key] for key in sorted(rounds)]


def _build_timeline(
    turn: Any,
    messages: list[dict[str, Any]],
    local_tools: list[dict[str, Any]],
    server_tools: list[dict[str, Any]],
    model_rounds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = [
        {
            "id": f"run-start:{turn.trace_id}",
            "at": turn.started_at,
            "kind": "run_start",
            "title": "Run started",
            "status": "running",
            "summary": f"{turn.graph_id} / {turn.node_id}",
            "details": {"trace_id": turn.trace_id, "provider_id": turn.provider_id},
        }
    ]
    for message in messages:
        role = str(message.get("role") or "")
        timeline.append(
            {
                "id": f"message:{message.get('id')}",
                "at": str(message.get("created_at") or ""),
                "kind": role,
                "title": "User" if role == "user" else "Assistant",
                "status": "completed",
                "summary": _message_text(message),
                "details": message,
            }
        )
    for item in model_rounds:
        timeline.append(
            {
                "id": f"model:{item['request_index']}",
                "at": item.get("started_at") or item.get("completed_at"),
                "kind": "model_round",
                "title": f"Model round {item['request_index']}",
                "status": "completed" if item.get("response") is not None else "incomplete",
                "summary": _model_round_summary(item),
                "details": item,
            }
        )
    for item in [*local_tools, *server_tools]:
        timeline.append(
            {
                "id": f"tool:{item['call_id']}",
                "at": item.get("started_at") or item.get("completed_at"),
                "kind": "tool_call",
                "title": str(item.get("name") or "tool"),
                "status": str(item.get("status") or ""),
                "summary": _tool_summary(item),
                "details": item,
            }
        )
    if turn.completed_at:
        timeline.append(
            {
                "id": f"run-end:{turn.trace_id}",
                "at": turn.completed_at,
                "kind": "run_end",
                "title": "Run completed",
                "status": turn.status,
                "summary": turn.error or _duration_text(turn.duration_ms),
                "details": {
                    "duration_ms": turn.duration_ms,
                    "error": turn.error,
                    "status": turn.status,
                },
            }
        )
    timeline.sort(key=lambda item: (str(item.get("at") or ""), str(item.get("id") or "")))
    return timeline


def _collect_file_changes(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for call in tool_calls:
        for artifact in call.get("artifacts") or []:
            data = artifact.get("data")
            if not isinstance(data, dict):
                continue
            operations = data.get("operations")
            if not isinstance(operations, list):
                continue
            for operation in operations:
                if not isinstance(operation, dict):
                    continue
                path = str(operation.get("path") or "").strip()
                if path:
                    changes[path] = {
                        "path": path,
                        "operation": str(operation.get("type") or operation.get("operation") or "change"),
                        "call_id": call.get("call_id"),
                        "artifact_path": artifact.get("path"),
                    }
    return sorted(changes.values(), key=lambda item: item["path"])


def _tool_messages_by_call(
    messages: list[dict[str, Any]],
    call_ids: set[str],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for message in messages:
        part = _first_tool_part(message)
        call_id = str(part.get("call_id") or "").strip()
        if call_id in call_ids:
            output[call_id] = message
    return output


def _first_tool_part(message: dict[str, Any]) -> dict[str, Any]:
    parts = message.get("parts")
    if not isinstance(parts, list):
        return {}
    return next(
        (part for part in parts if isinstance(part, dict) and part.get("type") == "tool_call"),
        {},
    )


def _message_result(part: dict[str, Any]) -> str:
    preview = str(part.get("result_preview") or "")
    tail = str(part.get("result_tail_preview") or "")
    if tail and tail not in preview:
        return preview + "\n…\n" + tail
    return preview


def _message_text(message: dict[str, Any]) -> str:
    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    return "\n".join(
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ).strip()


def _notice_payload(event: dict[str, Any]) -> dict[str, Any]:
    import json

    value = event.get("message_artifact", event.get("message"))
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _model_round_summary(item: dict[str, Any]) -> str:
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    response = item.get("response") if isinstance(item.get("response"), dict) else {}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    parts = [str(item.get("provider") or "model")]
    if request.get("approx_input_tokens") is not None:
        parts.append(f"~{request['approx_input_tokens']} input tokens")
    if usage.get("output_tokens") is not None:
        parts.append(f"{usage['output_tokens']} output tokens")
    return " · ".join(parts)


def _tool_summary(item: dict[str, Any]) -> str:
    if item.get("error"):
        return str(item["error"])
    if item.get("sources"):
        return f"{len(item['sources'])} sources"
    if item.get("artifacts"):
        return f"{len(item['artifacts'])} artifacts"
    return str(item.get("result_preview") or item.get("status") or "")


def _duration_text(value: int | None) -> str:
    if value is None:
        return ""
    return f"{value / 1000:.1f}s"


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["project_turn_detail"]
