from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from src.runtime_cancellation import cancel_source_from_agent, raise_if_cancel_requested
from src.workspace_settings import get_workspace_root

_ALLOWED_FIELD_TYPES = {"text", "textarea", "select", "multiselect", "checkbox", "file", "custom_html"}
_TERMINAL_STATUSES = {"submitted", "cancelled", "expired"}
_DEFAULT_TIMEOUT_SEC = 600
_MAX_TIMEOUT_SEC = 3600
_MAX_FIELDS = 20
_MAX_OPTIONS = 100
_MAX_CUSTOM_HTML_CHARS = 20000
_MAX_CUSTOM_CSS_CHARS = 12000
_MAX_CUSTOM_JS_CHARS = 20000


def _runtime_root() -> str:
    return get_workspace_root()


def _interaction_dir() -> str:
    path = os.path.join(_runtime_root(), "memories", "interactions")
    os.makedirs(path, exist_ok=True)
    return path


def _request_path(request_id: str) -> str:
    return os.path.join(_interaction_dir(), f"{request_id}.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[:limit]
    return text


def _safe_identifier(value: Any, *, fallback: str) -> str:
    raw = str(value or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    return (safe[:64] or fallback)


def _atomic_write_json(file_path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    tmp_path = f"{file_path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, file_path)


def _read_json(file_path: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("interaction request payload must be an object")
    return data


def _normalize_option(raw: Any, index: int) -> dict:
    if isinstance(raw, dict):
        value = _safe_text(raw.get("value"), limit=500)
        label = _safe_text(raw.get("label"), limit=500) or value
        disabled = bool(raw.get("disabled"))
    else:
        value = _safe_text(raw, limit=500)
        label = value
        disabled = False
    if not value:
        value = f"option_{index + 1}"
    return {"value": value, "label": label or value, "disabled": disabled}


def _normalize_field(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"fields[{index}] must be an object")

    field_id = _safe_identifier(raw.get("id") or raw.get("name"), fallback=f"field_{index + 1}")
    field_type = str(raw.get("type") or "text").strip().lower()
    if field_type not in _ALLOWED_FIELD_TYPES:
        raise ValueError(f"fields[{index}].type must be one of {sorted(_ALLOWED_FIELD_TYPES)}")

    field = {
        "id": field_id,
        "type": field_type,
        "label": _safe_text(raw.get("label"), limit=500) or field_id,
        "description": _safe_text(raw.get("description"), limit=1000),
        "placeholder": _safe_text(raw.get("placeholder"), limit=500),
        "required": bool(raw.get("required")),
    }

    if field_type == "custom_html":
        field["html"] = _safe_text(raw.get("html"), limit=_MAX_CUSTOM_HTML_CHARS)
        field["css"] = _safe_text(raw.get("css"), limit=_MAX_CUSTOM_CSS_CHARS)
        field["js"] = _safe_text(raw.get("js"), limit=_MAX_CUSTOM_JS_CHARS)
        field["height"] = max(180, min(int(float(raw.get("height") or 360)), 900))
        initial_data = raw.get("initial_data")
        field["initial_data"] = initial_data if isinstance(initial_data, dict) else {}
        if not field["html"]:
            raise ValueError(f"fields[{index}].html is required for custom_html")
        return field

    if "default" in raw:
        field["default"] = raw.get("default")
    if field_type in {"select", "multiselect"}:
        raw_options = raw.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise ValueError(f"fields[{index}].options is required for {field_type}")
        field["options"] = [_normalize_option(item, option_index) for option_index, item in enumerate(raw_options[:_MAX_OPTIONS])]
    if field_type == "file":
        field["accept"] = _safe_text(raw.get("accept"), limit=500)
        field["multiple"] = bool(raw.get("multiple"))
    return field


def normalize_interaction_schema(
    *,
    title: Any,
    description: Any = "",
    fields: Any = None,
    confirm_label: Any = "确认",
) -> dict:
    raw_fields = fields if isinstance(fields, list) else []
    normalized_fields = [_normalize_field(item, index) for index, item in enumerate(raw_fields[:_MAX_FIELDS])]
    if not normalized_fields:
        normalized_fields = [
            {
                "id": "message",
                "type": "textarea",
                "label": "补充信息",
                "description": "",
                "placeholder": "请输入要补充给 Agent 的内容",
                "required": True,
            }
        ]
    return {
        "title": _safe_text(title, limit=500) or "Agent 请求用户输入",
        "description": _safe_text(description, limit=4000),
        "confirm_label": _safe_text(confirm_label, limit=80) or "确认",
        "fields": normalized_fields,
    }


def _request_agent_context(agent: object | None) -> dict:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        config = {}
    return {
        "graph_id": _safe_text(config.get("graph_id"), limit=200),
        "node_id": _safe_text(config.get("node_instance_id") or config.get("node_id"), limit=200),
        "node_name": _safe_text(config.get("name"), limit=200),
    }


def create_interaction_request(
    *,
    schema: dict,
    timeout_sec: int | float,
    agent: object | None = None,
) -> dict:
    now = time.time()
    request_id = uuid.uuid4().hex
    timeout_value = max(1, min(int(float(timeout_sec or _DEFAULT_TIMEOUT_SEC)), _MAX_TIMEOUT_SEC))
    payload = {
        "id": request_id,
        "status": "pending",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "expires_at": now + timeout_value,
        "timeout_sec": timeout_value,
        "schema": schema,
        "agent": _request_agent_context(agent),
        "response": None,
    }
    _atomic_write_json(_request_path(request_id), payload)
    return payload


def read_interaction_request(request_id: str) -> dict:
    safe_id = _safe_identifier(request_id, fallback="")
    if not safe_id:
        raise FileNotFoundError("interaction request id is required")
    return _read_json(_request_path(safe_id))


def list_interaction_requests(status: str = "pending") -> list[dict]:
    requested_status = str(status or "pending").strip().lower()
    items: list[dict] = []
    directory = _interaction_dir()
    now = time.time()
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
        file_path = os.path.join(directory, filename)
        try:
            payload = _read_json(file_path)
        except Exception:
            continue
        if payload.get("status") == "pending" and float(payload.get("expires_at") or 0) <= now:
            payload["status"] = "expired"
            payload["updated_at"] = _now_iso()
            payload["response"] = {"error": "interaction request expired"}
            try:
                _atomic_write_json(file_path, payload)
            except Exception:
                pass
        if requested_status and requested_status != "all" and payload.get("status") != requested_status:
            continue
        items.append(payload)
    items.sort(key=lambda item: str(item.get("created_at") or ""))
    return items


def submit_interaction_response(request_id: str, response: Any, status: str = "submitted") -> dict:
    safe_id = _safe_identifier(request_id, fallback="")
    if not safe_id:
        raise FileNotFoundError("interaction request id is required")
    file_path = _request_path(safe_id)
    payload = _read_json(file_path)
    current_status = str(payload.get("status") or "").strip().lower()
    if current_status != "pending":
        raise ValueError(f"interaction request is already {current_status or 'closed'}")
    next_status = str(status or "submitted").strip().lower()
    if next_status not in _TERMINAL_STATUSES:
        raise ValueError(f"invalid interaction status: {next_status}")
    payload["status"] = next_status
    payload["updated_at"] = _now_iso()
    payload["response"] = response if isinstance(response, dict) else {"values": response}
    _atomic_write_json(file_path, payload)
    return payload


def wait_for_interaction_response(request_id: str, *, timeout_sec: int | float, agent: object | None = None) -> dict:
    deadline = time.monotonic() + max(1.0, float(timeout_sec or _DEFAULT_TIMEOUT_SEC))
    cancel_source = cancel_source_from_agent(agent)
    while True:
        raise_if_cancel_requested(cancel_source)
        payload = read_interaction_request(request_id)
        status = str(payload.get("status") or "pending").strip().lower()
        if status in _TERMINAL_STATUSES:
            return payload
        if time.monotonic() >= deadline:
            return submit_interaction_response(
                request_id,
                {"error": "interaction request timed out"},
                status="expired",
            )
        time.sleep(0.2)
