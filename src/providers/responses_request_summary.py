from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.providers.agent_environment_context import is_agent_environment_context_text
from src.providers.agent_collaboration_mode import is_collaboration_mode_text
from src.providers.agent_permissions_context import is_agent_permissions_context_text
from src.providers.agent_project_instructions import is_agent_project_instructions_text
from src.providers.agent_turn_context import is_agent_turn_context_text


MAX_LARGEST_INPUT_ITEMS = 8
MAX_INPUT_ITEMS_INCLUDED = 80
MAX_TOOLS_INCLUDED = 64


def build_responses_request_summary(
    *,
    request_index: int,
    current_input: Any,
    tools_payload: Any,
    stream: bool,
    responses_mode: str,
    requested_responses_mode: str,
    context_update: Any = None,
    instructions: str = "",
    tool_choice: str = "",
    parallel_tool_calls: bool | None = None,
    include: Any = None,
) -> dict[str, Any]:
    items = current_input if isinstance(current_input, list) else []
    item_summaries = [_summarize_input_item(index, item) for index, item in enumerate(items)]
    _attach_tool_result_names(item_summaries)
    _attach_context_kinds(item_summaries, items)
    tool_results = [item for item in item_summaries if item.get("type") == "function_call_output"]
    largest_tool_result = max(tool_results, key=lambda item: int(item.get("chars") or 0), default=None)
    tools_included = _tools_included(tools_payload)
    environment_context_chars = sum(_context_text_chars(raw, is_agent_environment_context_text) for raw in items)
    turn_context_chars = sum(_context_text_chars(raw, is_agent_turn_context_text) for raw in items)
    collaboration_context_chars = sum(_context_text_chars(raw, is_collaboration_mode_text) for raw in items)
    permissions_context_chars = sum(_context_text_chars(raw, is_agent_permissions_context_text) for raw in items)
    internal_context_chars = sum(_context_text_chars(raw, _is_internal_context_text) for raw in items)
    skills_context_chars = sum(_context_text_chars(raw, _is_skills_context_text) for raw in items)
    mcp_servers_context_chars = sum(_context_text_chars(raw, _is_mcp_servers_context_text) for raw in items)
    operational_memory_context_chars = sum(
        _context_text_chars(raw, _is_operational_memory_context_text) for raw in items
    )
    project_instructions_context_chars = sum(
        _context_text_chars(raw, is_agent_project_instructions_text) for raw in items
    )
    summary = {
        "request_index": int(request_index or 0),
        "responses_mode": str(responses_mode or "").strip(),
        "requested_responses_mode": str(requested_responses_mode or "").strip(),
        "instructions_present": bool(str(instructions or "").strip()),
        "instructions_chars": len(str(instructions or "")),
        "tool_choice": str(tool_choice or "").strip(),
        "parallel_tool_calls": parallel_tool_calls if isinstance(parallel_tool_calls, bool) else None,
        "include": [str(item) for item in include] if isinstance(include, list) else [],
        "input_item_count": len(items),
        "approx_input_chars": sum(int(item.get("chars") or 0) for item in item_summaries),
        "approx_input_tokens": _approx_input_tokens(current_input),
        "environment_context_chars": environment_context_chars,
        "turn_context_chars": turn_context_chars,
        "permissions_context_chars": permissions_context_chars,
        "collaboration_context_chars": collaboration_context_chars,
        "internal_context_chars": internal_context_chars,
        "skills_context_chars": skills_context_chars,
        "mcp_servers_context_chars": mcp_servers_context_chars,
        "operational_memory_context_chars": operational_memory_context_chars,
        "project_instructions_context_chars": project_instructions_context_chars,
        "input_items": item_summaries[:MAX_INPUT_ITEMS_INCLUDED],
        "largest_input_items": sorted(
            item_summaries,
            key=lambda item: int(item.get("chars") or 0),
            reverse=True,
        )[:MAX_LARGEST_INPUT_ITEMS],
        "tool_result_chars_by_call": [
            {
                "call_id": str(item.get("call_id") or ""),
                "name": str(item.get("name") or ""),
                "chars": int(item.get("chars") or 0),
                "status": str(item.get("status") or ""),
            }
            for item in tool_results
        ],
        "largest_tool_result": largest_tool_result,
        "tools_included": tools_included,
        "tools_included_count": len(tools_included),
        "stream": bool(stream),
    }
    if isinstance(context_update, dict):
        if context_update.get("context_item_hash"):
            summary["context_item_hash"] = str(context_update.get("context_item_hash") or "")
        if context_update.get("context_update_mode"):
            summary["context_update_mode"] = str(context_update.get("context_update_mode") or "")
        if context_update.get("persistent_context_update_mode"):
            summary["persistent_context_update_mode"] = str(context_update.get("persistent_context_update_mode") or "")
        if context_update.get("persistent_context_item_hash"):
            summary["persistent_context_item_hash"] = str(context_update.get("persistent_context_item_hash") or "")
        diff = context_update.get("context_diff")
        if isinstance(diff, dict):
            paths = []
            for key in ("changed_paths", "added_paths", "removed_paths"):
                value = diff.get(key)
                if isinstance(value, list):
                    paths.extend(str(item) for item in value if str(item or "").strip())
            summary["context_diff_paths"] = sorted(dict.fromkeys(paths))
    return summary


def empty_message_diagnostics_from_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    largest_tool = summary.get("largest_tool_result")
    largest_tool_chars = int(largest_tool.get("chars") or 0) if isinstance(largest_tool, dict) else 0
    largest_input_items = summary.get("largest_input_items") if isinstance(summary.get("largest_input_items"), list) else []
    diagnostic = {
        "provider_request": {
            "request_index": int(summary.get("request_index") or 0),
            "responses_mode": str(summary.get("responses_mode") or ""),
            "input_item_count": int(summary.get("input_item_count") or 0),
            "approx_input_chars": int(summary.get("approx_input_chars") or 0),
            "approx_input_tokens": int(summary.get("approx_input_tokens") or 0),
            "largest_input_items": largest_input_items[:MAX_LARGEST_INPUT_ITEMS],
            "largest_tool_result": largest_tool if isinstance(largest_tool, dict) else None,
        },
        "likely_cause": _empty_message_likely_cause(summary),
        "suggested_fix": (
            "Keep tool results compact, avoid repeating broad scans, and continue from the summarized evidence. "
            "If more data is needed, use a narrower tool call."
        ),
    }
    if largest_tool_chars > 0:
        diagnostic["largest_tool_result_chars"] = largest_tool_chars
    return diagnostic


def _empty_message_likely_cause(summary: dict[str, Any]) -> str:
    approx_chars = int(summary.get("approx_input_chars") or 0)
    largest_tool = summary.get("largest_tool_result")
    largest_tool_chars = int(largest_tool.get("chars") or 0) if isinstance(largest_tool, dict) else 0
    largest_tool_status = str(largest_tool.get("output_status") or "") if isinstance(largest_tool, dict) else ""
    if largest_tool_status == "tool_result_submission_error":
        return "compacted_large_tool_result_context"
    if largest_tool_chars >= 10000:
        return "large_tool_result_context"
    if approx_chars >= 50000:
        return "large_responses_input_context"
    if int(summary.get("input_item_count") or 0) >= 40:
        return "many_responses_input_items"
    return "empty_provider_output"


def _summarize_input_item(index: int, item: Any) -> dict[str, Any]:
    item_type = "item"
    if isinstance(item, dict):
        item_type = str(item.get("type") or item.get("role") or "item").strip() or "item"
    chars = _json_chars(item)
    summary: dict[str, Any] = {
        "index": int(index),
        "type": item_type,
        "chars": chars,
    }
    if isinstance(item, dict):
        for key in ("role", "name", "call_id", "status"):
            value = str(item.get(key) or "").strip()
            if value:
                summary[key] = value
        if "output" in item:
            summary["output_chars"] = _json_chars(item.get("output"))
            status = _status_from_json_text(item.get("output"))
            if status:
                summary["output_status"] = status
        if "content" in item:
            summary["content_chars"] = _json_chars(item.get("content"))
    return summary


def _is_environment_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() not in {"system", "user"}:
        return False
    content = item.get("content")
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict):
            continue
        if is_agent_environment_context_text(part.get("text")):
            return True
    return False


def _is_turn_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("type") != "message" or item.get("role") != "system":
        return False
    content = item.get("content")
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict):
            continue
        if is_agent_turn_context_text(part.get("text")):
            return True
    return False


def _is_collaboration_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() != "developer":
        return False
    content = item.get("content")
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict):
            continue
        if is_collaboration_mode_text(part.get("text")):
            return True
    return False


def _is_permissions_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() != "developer":
        return False
    content = item.get("content")
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict):
            continue
        if is_agent_permissions_context_text(part.get("text")):
            return True
    return False


def _is_internal_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    content = item.get("content")
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or "").strip()
        if _is_internal_context_text(text):
            return True
    return False


def _is_skills_context_item(item: Any) -> bool:
    return _is_message_with_context_text(item, _is_skills_context_text)


def _is_mcp_servers_context_item(item: Any) -> bool:
    return _is_message_with_context_text(item, _is_mcp_servers_context_text)


def _is_operational_memory_context_item(item: Any) -> bool:
    return _is_message_with_context_text(item, _is_operational_memory_context_text)


def _is_project_instructions_context_item(item: Any) -> bool:
    return _is_message_with_context_text(item, is_agent_project_instructions_text)


def _attach_tool_result_names(item_summaries: list[dict[str, Any]]) -> None:
    names_by_call_id: dict[str, str] = {}
    for item in item_summaries:
        if item.get("type") != "function_call":
            continue
        call_id = str(item.get("call_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if call_id and name:
            names_by_call_id[call_id] = name

    if not names_by_call_id:
        return

    for item in item_summaries:
        if item.get("type") != "function_call_output" or item.get("name"):
            continue
        call_id = str(item.get("call_id") or "").strip()
        name = names_by_call_id.get(call_id)
        if name:
            item["name"] = name


def _attach_context_kinds(item_summaries: list[dict[str, Any]], raw_items: list[Any]) -> None:
    for summary, raw in zip(item_summaries, raw_items):
        kinds = []
        if _is_environment_context_item(raw):
            kinds.append("environment")
        if _is_turn_context_item(raw):
            kinds.append("turn_context")
        if _is_permissions_context_item(raw):
            kinds.append("permissions")
        if _is_collaboration_context_item(raw):
            kinds.append("collaboration_mode")
        if _is_internal_context_item(raw):
            kinds.append("internal_context")
        if _is_skills_context_item(raw):
            kinds.append("skills")
        if _is_mcp_servers_context_item(raw):
            kinds.append("mcp_servers")
        if _is_operational_memory_context_item(raw):
            kinds.append("operational_memory")
        if _is_project_instructions_context_item(raw):
            kinds.append("project_instructions")
        if kinds:
            summary["context_kind"] = kinds[0] if len(kinds) == 1 else "runtime_context"
            summary["context_kinds"] = kinds


def _is_message_with_context_text(item: Any, predicate) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "").strip().lower() != "message":
        return False
    content = item.get("content")
    if not isinstance(content, list):
        return False
    for part in content:
        if isinstance(part, dict) and predicate(part.get("text")):
            return True
    return False


def _context_text_chars(item: Any, predicate) -> int:
    if not isinstance(item, dict):
        return 0
    content = item.get("content")
    if not isinstance(content, list):
        return 0
    total = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if predicate(text):
            total += len(str(text or ""))
    return total


def _is_internal_context_text(value: object) -> bool:
    text = str(value or "").strip()
    return text.startswith("<agentpark_internal_context") and text.endswith("</agentpark_internal_context>")


def _is_skills_context_text(value: object) -> bool:
    text = str(value or "").strip()
    return (
        text.startswith("<skills_instructions>")
        and text.endswith("</skills_instructions>")
    ) or (text.startswith("<skills>") and text.endswith("</skills>"))


def _is_mcp_servers_context_text(value: object) -> bool:
    text = str(value or "").strip()
    return text.startswith("<mcp_servers>") and text.endswith("</mcp_servers>")


def _is_operational_memory_context_text(value: object) -> bool:
    return str(value or "").strip().startswith("Operational memory for this node:")


def _tools_included(tools_payload: Any) -> list[str]:
    tools = []
    for item in tools_payload if isinstance(tools_payload, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name and isinstance(item.get("function"), dict):
            name = str(item["function"].get("name") or "").strip()
        if not name:
            name = str(item.get("type") or "").strip()
        if name:
            tools.append(name)
        if len(tools) >= MAX_TOOLS_INCLUDED:
            break
    return tools


def _status_from_json_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        payload = json.loads(value)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("status") or "").strip()


def _json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except Exception:
        return len(str(value or ""))


@lru_cache(maxsize=8)
def _tiktoken_encoding(model: str = ""):
    """Return a tiktoken encoding, or None if unavailable.

    Special tokens like ``<|endoftext|>`` appear naturally in tool results, logs,
    or user text and must be encoded as ordinary text to avoid raising
    ``ValueError: Encountered text corresponding to disallowed special token``.
    Callers must pass ``disallowed_special=()`` when encoding.
    """
    try:
        import tiktoken  # type: ignore
    except Exception:
        return None
    try:
        if model:
            return tiktoken.encoding_for_model(model)
    except Exception:
        pass
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _flatten_input_text(value: Any) -> str:
    """Flatten Responses-style input items into a single text string for token estimation."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "content", "output", "name", "arguments", "input"):
            if key in value:
                parts.append(_flatten_input_text(value.get(key)))
        for key, sub in value.items():
            if key in {"type", "role", "call_id", "status", "id", "content_type"}:
                parts.append(str(sub or ""))
                continue
            if key in {"text", "content", "output", "name", "arguments", "input"}:
                continue
            parts.append(_flatten_input_text(sub))
        return "\n".join(p for p in parts if p)
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_flatten_input_text(item) for item in value)
    return str(value)


def _approx_input_tokens(current_input: Any, model: str = "") -> int:
    """Return an approximate token count for request input.

    Tiktoken raises on disallowed special tokens (e.g. ``<|endoftext|>``) when
    user or tool output contains them literally. We pass ``disallowed_special=()``
    to treat all such tokens as normal text, and fall back to a rough character
    heuristic if tiktoken is unavailable or fails.
    """
    text = _flatten_input_text(current_input)
    if not text:
        return 0
    encoding = _tiktoken_encoding(model)
    if encoding is not None:
        try:
            return len(encoding.encode(text, disallowed_special=()))
        except Exception:
            pass
    # Fallback heuristic: ~4 chars per token for mixed text.
    return max(1, len(text) // 4)
