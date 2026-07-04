from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from src.file_transaction import atomic_write_text
from src.providers.agent_collaboration_mode import collaboration_mode_context
from src.providers.agent_permissions_context import build_agent_permissions_context
from src.providers.agent_project_instructions import project_instructions_text_hash
from src.providers.agent_runtime_context import get_agent_runtime_context


AGENT_TURN_CONTEXT_SCHEMA_VERSION = 1
AGENT_TURN_CONTEXT_TEXT_PREFIX = "[Agent Turn Context]\n"
AGENT_TURN_CONTEXT_REFERENCE_FILENAME = "agent_turn_context.json"
STABLE_ENVIRONMENT_CONTEXT_KEYS = ("workspace_path", "shell", "current_date", "timezone")
VOLATILE_ENVIRONMENT_CONTEXT_KEYS = ("request_time",)


def build_agent_turn_context_item(
    agent: object,
    *,
    environment_context: dict[str, Any] | None = None,
    project_instructions_context: dict[str, Any] | None = None,
    tools_payload: Any = None,
    responses_mode: str = "",
    requested_responses_mode: str = "",
) -> dict[str, Any]:
    """Build the stable per-request context baseline used for Codex-like diffs."""
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        config = {}

    item: dict[str, Any] = {
        "schema_version": AGENT_TURN_CONTEXT_SCHEMA_VERSION,
        "kind": "agent_turn_context",
        "provider": _provider_context(agent, config),
        "environment": _environment_context(environment_context or {}),
        "permissions": build_agent_permissions_context(agent, environment_context),
        "collaboration_mode": collaboration_mode_context(agent, config),
        "project_instructions": _project_instructions_context(project_instructions_context or {}),
        "responses": _responses_context(config, responses_mode, requested_responses_mode),
        "tools": _tools_context(tools_payload),
    }

    node_context = _node_context(agent)
    if node_context:
        item["node"] = node_context

    volatile_context = _volatile_context(environment_context or {})
    if volatile_context:
        item["volatile"] = volatile_context

    return _strip_empty(item)


def build_agent_turn_context_update(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    request_index: int,
) -> dict[str, Any]:
    stable_current = _stable_context_for_diff(current)
    stable_previous = _stable_context_for_diff(previous) if isinstance(previous, dict) else None
    current_hash = context_item_hash(stable_current)

    payload: dict[str, Any] = {
        "request_index": int(request_index or 0),
        "context_item_hash": current_hash,
        "context_item_schema_version": AGENT_TURN_CONTEXT_SCHEMA_VERSION,
    }
    if stable_previous is None:
        payload["context_update_mode"] = "full"
        payload["context_item"] = stable_current
        return payload

    diff = diff_context_items(stable_previous, stable_current)
    if not diff["changed_paths"] and not diff["added_paths"] and not diff["removed_paths"]:
        payload["context_update_mode"] = "unchanged"
        return payload

    payload["context_update_mode"] = "diff"
    payload["context_diff"] = diff
    return payload


def format_agent_turn_context_update(update: dict[str, Any]) -> str:
    payload = model_visible_context_update(update)
    return AGENT_TURN_CONTEXT_TEXT_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def is_agent_turn_context_text(value: object) -> bool:
    return isinstance(value, str) and value.startswith(AGENT_TURN_CONTEXT_TEXT_PREFIX)


def model_visible_context_update(update: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(update, dict):
        return {}
    mode = str(update.get("context_update_mode") or "").strip()
    payload: dict[str, Any] = {
        "kind": "agent_turn_context_update",
        "schema_version": AGENT_TURN_CONTEXT_SCHEMA_VERSION,
        "context_update_mode": mode,
        "context_item_hash": str(update.get("context_item_hash") or "").strip(),
    }
    if mode == "full" and isinstance(update.get("context_item"), dict):
        payload["context_item"] = update["context_item"]
    elif mode == "diff" and isinstance(update.get("context_diff"), dict):
        payload["context_diff"] = update["context_diff"]
    return _strip_empty(payload)


def load_agent_turn_context_reference(agent: object) -> dict[str, Any] | None:
    path = agent_turn_context_reference_path(agent)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    item = payload.get("context_item")
    return item if isinstance(item, dict) else None


def save_agent_turn_context_reference(agent: object, context_item: dict[str, Any]) -> None:
    path = agent_turn_context_reference_path(agent)
    if not path:
        return
    stable_item = _stable_context_for_diff(context_item)
    payload = {
        "schema_version": AGENT_TURN_CONTEXT_SCHEMA_VERSION,
        "context_item_hash": context_item_hash(stable_item),
        "context_item": stable_item,
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except OSError:
        return


def agent_turn_context_reference_path(agent: object) -> str:
    memory_path = str(getattr(agent, "current_memory_path", "") or "").strip()
    if not memory_path:
        memory = getattr(agent, "memory", None)
        memory_path = str(getattr(memory, "current_memory_path", "") or "").strip()
    if not memory_path:
        return ""
    memory_dir = os.path.dirname(os.path.abspath(memory_path))
    if not memory_dir:
        return ""
    return os.path.join(memory_dir, AGENT_TURN_CONTEXT_REFERENCE_FILENAME)


def context_item_hash(item: dict[str, Any]) -> str:
    text = json.dumps(item or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def diff_context_items(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = _flatten(previous)
    after = _flatten(current)
    before_keys = set(before)
    after_keys = set(after)
    changed = sorted(key for key in before_keys & after_keys if before[key] != after[key])
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)

    changes = []
    for path in [*changed, *added, *removed][:50]:
        entry: dict[str, Any] = {"path": path}
        if path in before:
            entry["previous"] = before[path]
        if path in after:
            entry["current"] = after[path]
        changes.append(entry)

    return {
        "changed_paths": changed,
        "added_paths": added,
        "removed_paths": removed,
        "changes": changes,
    }


def _provider_context(agent: object, config: dict[str, Any]) -> dict[str, Any]:
    provider_name = str(getattr(agent, "provider_name", "") or "").strip()
    keys = (
        "type",
        "model",
        "responsesApi",
        "responsesContinuationMode",
        "reasoningEffort",
        "responsesReplayReasoningItems",
    )
    provider = {key: config.get(key) for key in keys if key in config and _has_value(config.get(key))}
    if provider_name:
        provider["id"] = provider_name
    return _stringify_scalars(provider)


def _environment_context(context: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(context.get(key) or "").strip()
        for key in STABLE_ENVIRONMENT_CONTEXT_KEYS
        if str(context.get(key) or "").strip()
    }


def _volatile_context(context: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(context.get(key) or "").strip()
        for key in VOLATILE_ENVIRONMENT_CONTEXT_KEYS
        if str(context.get(key) or "").strip()
    }


def _project_instructions_context(context: dict[str, Any]) -> dict[str, Any]:
    paths = context.get("paths") if isinstance(context.get("paths"), list) else []
    safe_paths = [str(path).strip() for path in paths if str(path or "").strip()]
    result = {
        "directory": str(context.get("directory") or "").strip(),
        "paths": safe_paths,
        "chars": len(str(context.get("text") or "")),
        "text_hash": project_instructions_text_hash(context.get("text")),
    }
    return {key: value for key, value in result.items() if _has_value(value)}


def _responses_context(config: dict[str, Any], responses_mode: str, requested_responses_mode: str) -> dict[str, str]:
    context = {
        "responses_mode": str(responses_mode or "").strip(),
        "requested_responses_mode": str(requested_responses_mode or "").strip(),
    }
    continuation = str(config.get("responsesContinuationMode") or "").strip()
    if continuation:
        context["continuation_mode"] = continuation
    return {key: value for key, value in context.items() if value}


def _tools_context(tools_payload: Any) -> dict[str, Any]:
    names: list[str] = []
    for tool in tools_payload if isinstance(tools_payload, list) else []:
        if not isinstance(tool, dict):
            continue
        name = ""
        tool_type = str(tool.get("type") or "").strip()
        if tool_type in {"web_search", "web_search_preview"}:
            name = tool_type
        elif tool_type == "function":
            name = str(tool.get("name") or "").strip()
            if not name and isinstance(tool.get("function"), dict):
                name = str(tool["function"].get("name") or "").strip()
        if name:
            names.append(name)
    unique_names = sorted(dict.fromkeys(names))
    return {"names": unique_names, "count": len(unique_names)}


def _node_context(agent: object) -> dict[str, str]:
    runtime_context = get_agent_runtime_context(agent)
    values = {
        "node_type_id": runtime_context.node_type_id,
        "working_path": runtime_context.working_path,
    }
    result = {}
    for out_key, raw in values.items():
        value = str(raw or "").strip()
        if value:
            result[out_key] = value
    return result


def _stable_context_for_diff(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    stable = {key: value for key, value in item.items() if key != "volatile"}
    return _strip_empty(stable)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            child = _flatten(value[key], f"{prefix}.{key}" if prefix else str(key))
            result.update(child)
        return result
    if isinstance(value, list):
        return {prefix: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}
    return {prefix: value}


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            stripped = _strip_empty(child)
            if _has_value(stripped):
                result[key] = stripped
        return result
    if isinstance(value, list):
        return [_strip_empty(item) for item in value if _has_value(_strip_empty(item))]
    return value


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _stringify_scalars(payload: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            result[key] = value
        elif isinstance(value, (int, float)):
            result[key] = value
        elif value is not None:
            text = str(value).strip()
            if text:
                result[key] = text
    return result
