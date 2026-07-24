from __future__ import annotations

import hashlib
import json
from typing import Any

from src.providers.provider_message_policy import ProviderMessagePolicy


TOOL_CONTEXT_REPLACEMENT_PREFIX = "[Tool Context Replacement]"
TOOL_CONTEXT_REPLACEMENT_SCHEMA_VERSION = 1
MAX_ENTRY_TEXT_CHARS = 2400
MAX_COLLECTION_ITEMS = 20
MAX_NESTING_DEPTH = 4


def build_tool_context_replacement(
    candidates: list[dict[str, Any]],
    *,
    max_chars: int,
) -> str:
    entries = [_candidate_entry(candidate) for candidate in candidates]
    payload: dict[str, Any] = {
        "schema_version": TOOL_CONTEXT_REPLACEMENT_SCHEMA_VERSION,
        "kind": "tool_context_replacement",
        "message_count": len(candidates),
        "candidate_set_sha256": _digest([entry.get("content_sha256", "") for entry in entries]),
        "entries": [],
        "represented_entry_count": 0,
        "detail_entries_omitted": 0,
        "unrepresented_entry_count": len(entries),
    }
    if len(_format_payload(payload)) > max_chars:
        raise ValueError(
            f"tool context replacement metadata exceeds configured max_chars={max_chars}"
        )

    for entry in entries:
        if _append_entry_within_budget(payload, entry, total_entries=len(entries), max_chars=max_chars):
            continue
        break
    return _format_payload(payload)


def _append_entry_within_budget(
    payload: dict[str, Any],
    entry: dict[str, Any],
    *,
    total_entries: int,
    max_chars: int,
) -> bool:
    for candidate, omits_detail in ((entry, False), (_metadata_only_entry(entry), True)):
        trial = {**payload, "entries": [*payload["entries"], candidate]}
        represented_count = len(trial["entries"])
        trial["represented_entry_count"] = represented_count
        trial["unrepresented_entry_count"] = total_entries - represented_count
        trial["detail_entries_omitted"] = int(payload["detail_entries_omitted"]) + int(omits_detail)
        if len(_format_payload(trial)) <= max_chars:
            payload.clear()
            payload.update(trial)
            return True
    return False


def is_tool_context_replacement_message(message: object) -> bool:
    return (
        isinstance(message, dict)
        and ProviderMessagePolicy.is_instruction_message(message)
        and str(message.get("content") or "").startswith(TOOL_CONTEXT_REPLACEMENT_PREFIX)
    )


def _candidate_entry(candidate: dict[str, Any]) -> dict[str, Any]:
    content = candidate.get("content")
    decoded = _decode_json_object(content)
    entry: dict[str, Any] = {
        "message_id": str(candidate.get("message_id") or ""),
        "role": str(candidate.get("role") or ""),
        "name": str(candidate.get("name") or ""),
        "tool_call_id": str(candidate.get("tool_call_id") or ""),
        "content_sha256": _digest(content),
    }
    tool_calls = candidate.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        entry["tool_calls"] = _bounded_value(tool_calls, depth=0)
    if decoded is not None:
        entry["result"] = _bounded_value(decoded, depth=0)
    elif content not in (None, ""):
        entry["content_preview"] = _bounded_text(content)
    return {key: value for key, value in entry.items() if value not in ("", None, [], {})}


def _metadata_only_entry(entry: dict[str, Any]) -> dict[str, Any]:
    keys = ("message_id", "role", "name", "tool_call_id", "content_sha256")
    return {key: entry[key] for key in keys if key in entry}


def _bounded_value(value: Any, *, depth: int) -> Any:
    if depth >= MAX_NESTING_DEPTH:
        return {"truncated": True, "sha256": _digest(value)}
    if isinstance(value, dict):
        items = list(value.items())
        result = {
            str(key): _bounded_value(child, depth=depth + 1)
            for key, child in items[:MAX_COLLECTION_ITEMS]
        }
        if len(items) > MAX_COLLECTION_ITEMS:
            result["_omitted_key_count"] = len(items) - MAX_COLLECTION_ITEMS
        return result
    if isinstance(value, list):
        result = [
            _bounded_value(child, depth=depth + 1)
            for child in value[:MAX_COLLECTION_ITEMS]
        ]
        if len(value) > MAX_COLLECTION_ITEMS:
            result.append({"omitted_item_count": len(value) - MAX_COLLECTION_ITEMS})
        return result
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _bounded_text(str(value))


def _bounded_text(value: object) -> str:
    text = str(value or "")
    if len(text) <= MAX_ENTRY_TEXT_CHARS:
        return text
    return text[:MAX_ENTRY_TEXT_CHARS] + f"\n...[{len(text) - MAX_ENTRY_TEXT_CHARS} chars omitted; sha256={_digest(text)}]"


def _decode_json_object(value: object) -> dict[str, Any] | list[Any] | None:
    if not isinstance(value, str):
        return value if isinstance(value, (dict, list)) else None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, (dict, list)) else None


def _digest(value: object) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _format_payload(payload: dict[str, Any]) -> str:
    return TOOL_CONTEXT_REPLACEMENT_PREFIX + "\n" + json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
