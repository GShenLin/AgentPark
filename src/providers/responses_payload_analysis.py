from __future__ import annotations

import json
import os
from typing import Any

from src.providers.agent_collaboration_mode import is_collaboration_mode_text
from src.providers.agent_environment_context import is_agent_environment_context_text
from src.providers.agent_permissions_context import is_agent_permissions_context_text
from src.providers.agent_project_instructions import is_agent_project_instructions_text


def analyze_responses_payload_log(path: str) -> dict[str, Any]:
    normalized_path = os.path.abspath(os.path.expanduser(str(path or "")))
    if not os.path.isfile(normalized_path):
        return {
            "path": normalized_path,
            "exists": False,
            "record_count": 0,
            "requests": [],
            "gaps": [f"payload log does not exist: {normalized_path}"],
        }

    records = _load_jsonl(normalized_path)
    requests = [summarize_payload_record(record) for record in records]
    gaps = _codex_like_gaps(requests)
    return {
        "path": normalized_path,
        "exists": True,
        "record_count": len(records),
        "requests": requests,
        "gaps": gaps,
        "codex_reference": {
            "instructions": "Responses payload instructions",
            "runtime_context": "developer/user input items recorded in conversation history",
            "turn_context_item": "durable rollout baseline, not raw model input text",
            "source_files": [
                "codex-rs/core/src/session/mod.rs",
                "codex-rs/core/src/session/turn.rs",
                "codex-rs/core/src/session/turn_context.rs",
                "codex-rs/core/src/client.rs",
            ],
        },
    }


def summarize_payload_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload") if isinstance(record, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    input_items = payload.get("input") if isinstance(payload.get("input"), list) else []
    request_summary = record.get("request_summary") if isinstance(record, dict) else None
    if not isinstance(request_summary, dict):
        request_summary = {}

    item_summaries = [_summarize_input_item(index, item) for index, item in enumerate(input_items)]
    context_kind_counts = _context_kind_counts(input_items)
    return {
        "request_index": int(record.get("request_index") or request_summary.get("request_index") or 0)
        if isinstance(record, dict)
        else 0,
        "model": str(payload.get("model") or ""),
        "previous_response_id_present": bool(str(payload.get("previous_response_id") or "").strip()),
        "instructions_present": bool(str(payload.get("instructions") or "").strip()),
        "instructions_chars": len(str(payload.get("instructions") or "")),
        "tool_choice": str(payload.get("tool_choice") or "").strip(),
        "parallel_tool_calls": payload.get("parallel_tool_calls") if isinstance(payload.get("parallel_tool_calls"), bool) else None,
        "include": [str(item) for item in payload.get("include")] if isinstance(payload.get("include"), list) else [],
        "reasoning_present": isinstance(payload.get("reasoning"), dict),
        "input_item_count": len(input_items),
        "roles": [
            str(item.get("role") or item.get("type") or "").strip()
            for item in input_items
            if isinstance(item, dict)
        ],
        "input_items": item_summaries,
        "context_kind_counts": context_kind_counts,
        "tools_included_count": len(payload.get("tools")) if isinstance(payload.get("tools"), list) else 0,
        "summary": {
            key: request_summary.get(key)
            for key in (
                "responses_mode",
                "requested_responses_mode",
                "context_update_mode",
                "persistent_context_update_mode",
                "approx_input_chars",
                "approx_input_tokens",
                "tool_choice",
                "parallel_tool_calls",
                "include",
            )
            if key in request_summary
        },
    }


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                records.append(
                    {
                        "stage": "jsonl_parse_error",
                        "request_index": 0,
                        "payload": {},
                        "error": f"line {line_number}: {exc}",
                    }
                )
                continue
            if isinstance(payload, dict):
                records.append(payload)
    return records


def _summarize_input_item(index: int, item: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "index": index,
        "type": str(item.get("type") or "item") if isinstance(item, dict) else type(item).__name__,
        "chars": len(json.dumps(item, ensure_ascii=False, sort_keys=True)),
    }
    if isinstance(item, dict):
        for key in ("role", "name", "call_id", "status"):
            value = str(item.get(key) or "").strip()
            if value:
                summary[key] = value
        kinds = _context_kinds(item)
        if kinds:
            summary["context_kind"] = kinds[0] if len(kinds) == 1 else "runtime_context"
            summary["context_kinds"] = kinds
        if "output" in item:
            summary["output_chars"] = len(str(item.get("output") or ""))
    return summary


def _context_kinds(item: dict[str, Any]) -> list[str]:
    content = item.get("content")
    if not isinstance(content, list):
        return []
    kinds: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if is_agent_permissions_context_text(text) and "permissions" not in kinds:
            kinds.append("permissions")
        if is_collaboration_mode_text(text) and "collaboration_mode" not in kinds:
            kinds.append("collaboration_mode")
        if is_agent_environment_context_text(text) and "environment" not in kinds:
            kinds.append("environment")
        if is_agent_project_instructions_text(text) and "project_instructions" not in kinds:
            kinds.append("project_instructions")
        raw_text = str(text or "").strip()
        if _is_skills_context_text(raw_text) and "skills" not in kinds:
            kinds.append("skills")
        if raw_text.startswith("<mcp_servers>") and raw_text.endswith("</mcp_servers>") and "mcp_servers" not in kinds:
            kinds.append("mcp_servers")
        if raw_text.startswith("Operational memory for this node:") and "operational_memory" not in kinds:
            kinds.append("operational_memory")
        if raw_text.startswith("<agentpark_internal_context") and raw_text.endswith("</agentpark_internal_context>"):
            if "internal_context" not in kinds:
                kinds.append("internal_context")
    return kinds


def _context_kind_counts(items: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            for kind in _context_kinds({"content": [part]}):
                counts[kind] = counts.get(kind, 0) + 1
    return counts


def _codex_like_gaps(requests: list[dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    if not requests:
        return ["payload log has no request records"]

    first = requests[0]
    first_roles = first.get("roles") if isinstance(first.get("roles"), list) else []
    if not first.get("instructions_present"):
        gaps.append("payload.instructions is absent; compare whether node instruction/default instructions were empty")
    if "developer" not in first_roles[:2]:
        gaps.append("first request does not start with a developer context item")
    if not _request_has_context(first, "permissions"):
        gaps.append("first request lacks developer permissions context")
    if not _request_has_context(first, "environment"):
        gaps.append("first request lacks user environment context")
    if _split_contextual_user_item_count(first) > 1:
        gaps.append("first request splits contextual user runtime context across multiple user messages")
    for request in requests:
        tools_count = int(request.get("tools_included_count") or 0)
        if tools_count > 0 and request.get("tool_choice") != "auto":
            gaps.append(f"request {request.get('request_index')} has tools but lacks Codex-style tool_choice=auto")
        if tools_count > 0 and request.get("parallel_tool_calls") is not True:
            gaps.append(f"request {request.get('request_index')} has tools but lacks Codex-style parallel_tool_calls=true")
        include = request.get("include") if isinstance(request.get("include"), list) else []
        if request.get("reasoning_present") and "reasoning.encrypted_content" not in include:
            gaps.append(
                f"request {request.get('request_index')} has reasoning but lacks include=reasoning.encrypted_content"
            )
        kind_counts = request.get("context_kind_counts") if isinstance(request.get("context_kind_counts"), dict) else {}
        for kind in ("permissions", "collaboration_mode", "environment", "project_instructions", "operational_memory"):
            count = int(kind_counts.get(kind) or 0)
            if count > 1:
                gaps.append(f"request {request.get('request_index')} repeats {kind} context parts {count} times")

    for request in requests[1:]:
        if first.get("instructions_present") and not request.get("instructions_present"):
            gaps.append(
                f"request {request.get('request_index')} lacks payload.instructions even though the first request had instructions"
            )
        for kind in ("permissions", "environment", "project_instructions"):
            count = _request_context_count(request, kind)
            if count > 1:
                gaps.append(
                    f"request {request.get('request_index')} repeats {kind} context {count} times"
                )
        if _split_contextual_user_item_count(request) > 1:
            gaps.append(
                f"request {request.get('request_index')} splits contextual user runtime context across multiple user messages"
            )
        if not request.get("previous_response_id_present"):
            continue
        if _request_has_context(request, "permissions") or _request_has_context(request, "environment"):
            gaps.append(
                f"request {request.get('request_index')} uses previous_response_id but still repeats runtime context"
            )
    return gaps


def _request_has_context(request: dict[str, Any], kind: str) -> bool:
    return _request_context_count(request, kind) > 0


def _request_context_count(request: dict[str, Any], kind: str) -> int:
    count = 0
    for item in request.get("input_items") if isinstance(request.get("input_items"), list) else []:
        kinds = item.get("context_kinds") if isinstance(item, dict) else None
        if isinstance(kinds, list) and kind in kinds:
            count += 1
    return count


def _split_contextual_user_item_count(request: dict[str, Any]) -> int:
    count = 0
    for item in request.get("input_items") if isinstance(request.get("input_items"), list) else []:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        kinds = item.get("context_kinds")
        if not isinstance(kinds, list):
            continue
        if "environment" in kinds or "project_instructions" in kinds:
            count += 1
    return count


def _is_skills_context_text(text: str) -> bool:
    return (
        text.startswith("<skills_instructions>")
        and text.endswith("</skills_instructions>")
    ) or (text.startswith("<skills>") and text.endswith("</skills>"))
