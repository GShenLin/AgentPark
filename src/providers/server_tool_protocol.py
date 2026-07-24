from __future__ import annotations

import copy
from typing import Any


SERVER_TOOL_ACTIVITY = "server_tool_activity"
SERVER_TOOL_ITEM_SUFFIX = "_call"


def is_server_tool_item_type(value: object) -> bool:
    item_type = str(value or "").strip().lower()
    return bool(item_type.endswith(SERVER_TOOL_ITEM_SUFFIX) and item_type != "function_call")


def server_tool_name(item_type: object) -> str:
    value = str(item_type or "").strip().lower()
    return value[: -len(SERVER_TOOL_ITEM_SUFFIX)] if is_server_tool_item_type(value) else value


def normalize_server_tool_call(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    item_type = str(item.get("type") or "").strip().lower()
    if not is_server_tool_item_type(item_type):
        return None
    call_id = str(item.get("id") or item.get("call_id") or "").strip()
    if not call_id:
        return None
    payload: dict[str, Any] = {
        "call_id": call_id,
        "tool_type": server_tool_name(item_type),
        "status": str(item.get("status") or "completed").strip().lower() or "completed",
        "details": copy.deepcopy(item),
    }
    action = item.get("action")
    if isinstance(action, dict) and action:
        payload["action"] = dict(action)
    sources = normalize_sources((action or {}).get("sources") if isinstance(action, dict) else None)
    if sources:
        payload["sources"] = sources
    for key in ("query", "search_query", "queries", "prompt", "result", "revised_prompt", "partial_image_index"):
        if key in item:
            payload["details"][key] = copy.deepcopy(item.get(key))
    return payload


def build_server_tool_activity(
    item: object,
    *,
    status: object = "",
    provider: object = "",
) -> dict[str, Any] | None:
    call = normalize_server_tool_call(item)
    if call is None:
        return None
    resolved_status = str(status or call.get("status") or "").strip().lower()
    payload: dict[str, Any] = {
        "type": SERVER_TOOL_ACTIVITY,
        **call,
        "status": resolved_status or "in_progress",
    }
    provider_text = str(provider or "").strip()
    if provider_text:
        payload["provider"] = provider_text
    return payload


def extract_responses_server_tool_result(result: object) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    calls: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    output = result.get("output")
    for item in output if isinstance(output, list) else []:
        call = normalize_server_tool_call(item)
        if call is not None:
            calls.append(call)
        if not isinstance(item, dict) or str(item.get("type") or "").strip().lower() != "message":
            continue
        content = item.get("content")
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            citations.extend(normalize_citations(part.get("annotations")))
    citations.extend(normalize_response_citations(result.get("citations")))
    payload: dict[str, Any] = {}
    if calls:
        payload["server_tool_calls"] = calls
    if citations:
        payload["citations"] = _deduplicate_by_url(citations)
    response_metadata = normalize_responses_metadata(result)
    if response_metadata:
        payload["response_metadata"] = response_metadata
    return payload


def normalize_responses_metadata(result: object) -> dict[str, Any]:
    """Preserve the provider response without coupling consumers to one vendor.

    Output items are intentionally retained in full.  The normalized indexes
    above make common server-tool and citation use cases convenient, while this
    snapshot prevents provider additions from being silently discarded.
    """
    if not isinstance(result, dict):
        return {}
    response_fields = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key != "output"
    }
    output = result.get("output")
    payload: dict[str, Any] = {
        "protocol": "responses",
        "response": response_fields,
        "output_items": copy.deepcopy(output) if isinstance(output, list) else [],
    }
    return payload


def normalize_response_citations(value: object) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            url = item.strip()
            if url:
                citations.append({"url": url})
            continue
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        citation: dict[str, Any] = {"url": url}
        title = str(item.get("title") or item.get("label") or "").strip()
        if title:
            citation["title"] = title
        citations.append(citation)
    return citations


def normalize_sources(value: object) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        source: dict[str, Any] = {"url": url}
        title = str(item.get("title") or item.get("name") or "").strip()
        if title:
            source["title"] = title
        source_type = str(item.get("type") or "").strip()
        if source_type:
            source["type"] = source_type
        sources.append(source)
    return _deduplicate_by_url(sources)


def normalize_citations(value: object) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        citation = item.get("url_citation") if isinstance(item.get("url_citation"), dict) else item
        citation_type = str(item.get("type") or citation.get("type") or "").strip().lower()
        if citation_type not in {"url_citation", "web_search", "web_search_result"}:
            continue
        url = str(citation.get("url") or "").strip()
        if not url:
            continue
        normalized: dict[str, Any] = {"url": url}
        title = str(citation.get("title") or "").strip()
        if title:
            normalized["title"] = title
        for key in ("start_index", "end_index"):
            value_at_key = citation.get(key)
            if isinstance(value_at_key, int) and not isinstance(value_at_key, bool):
                normalized[key] = value_at_key
        citations.append(normalized)
    return citations


def _deduplicate_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        output.append(item)
    return output
