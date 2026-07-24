from __future__ import annotations

import json
import math
from typing import Any

from src.providers.agent_environment_context import is_agent_environment_context_text
from src.providers.agent_collaboration_mode import is_collaboration_mode_text
from src.providers.agent_permissions_context import is_agent_permissions_context_text
from src.providers.agent_project_instructions import is_agent_project_instructions_text
from src.providers.agent_turn_context import is_agent_turn_context_text


MAX_LARGEST_INPUT_ITEMS = 8
MAX_INPUT_ITEMS_INCLUDED = 80
MAX_TOOLS_INCLUDED = 64
PROVIDER_REQUEST_INDEX_ATTR = "_agentpark_provider_request_index"


def next_provider_request_index(agent: object) -> int:
    try:
        current = int(getattr(agent, PROVIDER_REQUEST_INDEX_ATTR, 0) or 0)
    except Exception:
        current = 0
    next_index = current + 1
    setattr(agent, PROVIDER_REQUEST_INDEX_ATTR, next_index)
    return next_index


def build_provider_request_summary(
    *,
    request_index: int,
    current_input: Any,
    tools_payload: Any,
    stream: bool,
    request_api: str,
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
    tool_calls = _tool_call_chars_by_call(items)
    _attach_tool_result_names_from_calls(item_summaries, tool_calls)
    tool_results = [item for item in item_summaries if _is_tool_result_summary(item)]
    largest_tool_result = max(tool_results, key=lambda item: int(item.get("chars") or 0), default=None)
    tools_included = _tools_included(tools_payload)
    approx_input_chars = sum(int(item.get("chars") or 0) for item in item_summaries)
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
        "request_api": str(request_api or "").strip(),
        "responses_mode": str(responses_mode or "").strip(),
        "requested_responses_mode": str(requested_responses_mode or "").strip(),
        "instructions_present": bool(str(instructions or "").strip()),
        "instructions_chars": len(str(instructions or "")),
        "tool_choice": str(tool_choice or "").strip(),
        "parallel_tool_calls": parallel_tool_calls if isinstance(parallel_tool_calls, bool) else None,
        "include": [str(item) for item in include] if isinstance(include, list) else [],
        "input_item_count": len(items),
        "approx_input_chars": approx_input_chars,
        "approx_input_tokens": _approx_input_tokens(current_input, serialized_chars=approx_input_chars),
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
        "tool_call_chars_by_call": tool_calls,
        "tool_call_chars_total": sum(int(item.get("chars") or 0) for item in tool_calls),
        "tool_result_chars_total": sum(int(item.get("chars") or 0) for item in tool_results),
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
        tool_call_id = str(item.get("tool_call_id") or "").strip()
        if tool_call_id and not summary.get("call_id"):
            summary["call_id"] = tool_call_id
        if "output" in item:
            summary["output_chars"] = _json_chars(item.get("output"))
            status = _status_from_json_text(item.get("output"))
            if status:
                summary["output_status"] = status
        if "content" in item:
            summary["content_chars"] = _json_chars(item.get("content"))
            if str(item.get("role") or "").strip().lower() == "tool":
                summary["output_chars"] = _json_chars(item.get("content"))
                status = _status_from_json_text(item.get("content"))
                if status:
                    summary["output_status"] = status
    return summary


def _is_tool_result_summary(item: dict[str, Any]) -> bool:
    item_type = str(item.get("type") or "").strip().lower()
    role = str(item.get("role") or "").strip().lower()
    return item_type == "function_call_output" or item_type == "tool" or role == "tool"


def _is_environment_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    item_type = str(item.get("type") or "message").strip().lower()
    if item_type != "message":
        return False
    if str(item.get("role") or "").strip().lower() not in {"system", "user"}:
        return False
    return _content_has_text(item.get("content"), is_agent_environment_context_text)


def _is_turn_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    item_type = str(item.get("type") or "message").strip().lower()
    if item_type != "message" or item.get("role") != "system":
        return False
    return _content_has_text(item.get("content"), is_agent_turn_context_text)


def _is_collaboration_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "message").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() != "developer":
        return False
    return _content_has_text(item.get("content"), is_collaboration_mode_text)


def _is_permissions_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "message").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() != "developer":
        return False
    return _content_has_text(item.get("content"), is_agent_permissions_context_text)


def _is_internal_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "message").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    return _content_has_text(item.get("content"), _is_internal_context_text)


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


def _attach_tool_result_names_from_calls(item_summaries: list[dict[str, Any]], tool_calls: list[dict[str, Any]]) -> None:
    names_by_call_id = {
        str(item.get("call_id") or "").strip(): str(item.get("name") or "").strip()
        for item in tool_calls
        if str(item.get("call_id") or "").strip() and str(item.get("name") or "").strip()
    }
    if not names_by_call_id:
        return
    for item in item_summaries:
        if not _is_tool_result_summary(item) or item.get("name"):
            continue
        name = names_by_call_id.get(str(item.get("call_id") or "").strip())
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


def _tool_call_chars_by_call(raw_items: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "function_call":
            chars = _json_chars(item.get("arguments")) if "arguments" in item else 0
            calls.append(
                {
                    "call_id": str(item.get("call_id") or item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "chars": chars,
                }
            )
            continue
        tool_calls = item.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function_payload = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                arguments = function_payload.get("arguments") if isinstance(function_payload, dict) else tool_call.get("arguments")
                calls.append(
                    {
                        "call_id": str(tool_call.get("id") or tool_call.get("call_id") or ""),
                        "name": str(
                            (function_payload.get("name") if isinstance(function_payload, dict) else "")
                            or tool_call.get("name")
                            or ""
                        ),
                        "chars": _json_chars(arguments),
                    }
                )
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if str(part.get("type") or "").strip().lower() != "tool_use":
                    continue
                calls.append(
                    {
                        "call_id": str(part.get("id") or part.get("call_id") or ""),
                        "name": str(part.get("name") or ""),
                        "chars": _json_chars(part.get("input")),
                    }
                )
    return calls


def _is_message_with_context_text(item: Any, predicate) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "message").strip().lower() != "message":
        return False
    return _content_has_text(item.get("content"), predicate)


def _context_text_chars(item: Any, predicate) -> int:
    if not isinstance(item, dict):
        return 0
    return _content_text_chars(item.get("content"), predicate)


def _content_has_text(content: Any, predicate) -> bool:
    if isinstance(content, str):
        return bool(predicate(content))
    if not isinstance(content, list):
        return False
    for part in content:
        if isinstance(part, str) and predicate(part):
            return True
        if isinstance(part, dict) and predicate(part.get("text")):
            return True
    return False


def _content_text_chars(content: Any, predicate) -> int:
    if isinstance(content, str):
        return len(content) if predicate(content) else 0
    if not isinstance(content, list):
        return 0
    total = 0
    for part in content:
        if isinstance(part, str):
            if predicate(part):
                total += len(part)
            continue
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


def _approx_input_tokens(current_input: Any, *, serialized_chars: int) -> int:
    """Estimate diagnostic token volume without tokenizing the full request.

    This value is intentionally approximate and is not used for billing or
    context admission. Actual provider usage remains authoritative. Counting
    text classes avoids allocating a second request-sized string and prevents
    CPU-bound tokenizer work from blocking the web server during concurrent
    agent turns.
    """
    ascii_chars, non_ascii_chars = _text_character_profile(current_input)
    structural_chars = max(0, int(serialized_chars or 0) - ascii_chars - non_ascii_chars)
    estimate = (
        math.ceil(ascii_chars / 4)
        + non_ascii_chars
        + math.ceil(structural_chars / 4)
    )
    return max(1, estimate) if serialized_chars > 0 else 0


def _text_character_profile(value: Any) -> tuple[int, int]:
    if isinstance(value, str):
        if value.isascii():
            return (len(value), 0)
        ascii_chars = len(value.encode("ascii", errors="ignore"))
        return (ascii_chars, len(value) - ascii_chars)
    if isinstance(value, dict):
        ascii_total = 0
        non_ascii_total = 0
        for key, child in value.items():
            key_ascii, key_non_ascii = _text_character_profile(str(key))
            child_ascii, child_non_ascii = _text_character_profile(child)
            ascii_total += key_ascii + child_ascii
            non_ascii_total += key_non_ascii + child_non_ascii
        return (ascii_total, non_ascii_total)
    if isinstance(value, (list, tuple, set)):
        ascii_total = 0
        non_ascii_total = 0
        for child in value:
            child_ascii, child_non_ascii = _text_character_profile(child)
            ascii_total += child_ascii
            non_ascii_total += child_non_ascii
        return (ascii_total, non_ascii_total)
    if value is None:
        return (0, 0)
    return _text_character_profile(str(value))
