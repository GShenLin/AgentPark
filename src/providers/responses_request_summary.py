from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.providers.agent_environment_context import is_agent_environment_context_text


MAX_LARGEST_INPUT_ITEMS = 8
MAX_TOOLS_INCLUDED = 64


def build_responses_request_summary(
    *,
    request_index: int,
    continuation_mode: str,
    previous_response_id: str,
    current_input: Any,
    tools_payload: Any,
    stream: bool,
    responses_mode: str,
    requested_responses_mode: str,
) -> dict[str, Any]:
    items = current_input if isinstance(current_input, list) else []
    item_summaries = [_summarize_input_item(index, item) for index, item in enumerate(items)]
    _attach_tool_result_names(item_summaries)
    tool_results = [item for item in item_summaries if item.get("type") == "function_call_output"]
    largest_tool_result = max(tool_results, key=lambda item: int(item.get("chars") or 0), default=None)
    tools_included = _tools_included(tools_payload)
    environment_context_chars = sum(
        int(item.get("chars") or 0)
        for item, raw in zip(item_summaries, items)
        if _is_environment_context_item(raw)
    )
    return {
        "request_index": int(request_index or 0),
        "continuation_mode": str(continuation_mode or "").strip(),
        "responses_mode": str(responses_mode or "").strip(),
        "requested_responses_mode": str(requested_responses_mode or "").strip(),
        "previous_response_id_present": bool(str(previous_response_id or "").strip()),
        "input_item_count": len(items),
        "approx_input_chars": sum(int(item.get("chars") or 0) for item in item_summaries),
        "approx_input_tokens": _approx_input_tokens(current_input),
        "environment_context_chars": environment_context_chars,
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


def empty_message_diagnostics_from_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    largest_tool = summary.get("largest_tool_result")
    largest_tool_chars = int(largest_tool.get("chars") or 0) if isinstance(largest_tool, dict) else 0
    largest_input_items = summary.get("largest_input_items") if isinstance(summary.get("largest_input_items"), list) else []
    diagnostic = {
        "provider_request": {
            "request_index": int(summary.get("request_index") or 0),
            "continuation_mode": str(summary.get("continuation_mode") or ""),
            "responses_mode": str(summary.get("responses_mode") or ""),
            "input_item_count": int(summary.get("input_item_count") or 0),
            "approx_input_chars": int(summary.get("approx_input_chars") or 0),
            "approx_input_tokens": int(summary.get("approx_input_tokens") or 0),
            "previous_response_id_present": bool(summary.get("previous_response_id_present")),
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
    if str(item.get("role") or "").strip().lower() != "system":
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
