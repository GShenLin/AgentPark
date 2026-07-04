from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any


RESPONSES_PAYLOAD_LOG_FILENAME = "responses_payloads.jsonl"
SECRET_KEY_PARTS = ("apikey", "api_key", "authorization", "bearer", "token", "secret", "password")


def write_responses_payload_log(
    agent: object,
    *,
    request_index: int,
    payload: dict[str, Any],
    request_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = responses_payload_log_path(agent)
    if not path:
        return {}

    record = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "stage": "openai_responses_request_payload",
        "provider": str(getattr(agent, "provider_name", "") or "").strip(),
        "request_index": int(request_index or 0),
        "payload": sanitize_responses_payload(payload),
    }
    if isinstance(request_summary, dict):
        record["request_summary"] = _summary_for_payload_log(request_summary)

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError as exc:
        return {
            "request_index": int(request_index or 0),
            "path": path,
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "request_index": int(request_index or 0),
        "path": path,
        "payload_chars": len(json.dumps(record["payload"], ensure_ascii=False, sort_keys=True)),
    }


def responses_payload_log_path(agent: object) -> str:
    memory_path = str(getattr(agent, "current_memory_path", "") or "").strip()
    if not memory_path:
        memory = getattr(agent, "memory", None)
        memory_path = str(getattr(memory, "current_memory_path", "") or "").strip()
    if not memory_path:
        return ""
    memory_dir = os.path.dirname(os.path.abspath(memory_path))
    if not memory_dir:
        return ""
    return os.path.join(memory_dir, RESPONSES_PAYLOAD_LOG_FILENAME)


def sanitize_responses_payload(value: Any) -> Any:
    if isinstance(value, dict):
        output = {}
        for key, child in value.items():
            text_key = str(key)
            if _is_secret_key(text_key):
                output[text_key] = "[redacted]"
            else:
                output[text_key] = sanitize_responses_payload(child)
        return output
    if isinstance(value, list):
        return [sanitize_responses_payload(item) for item in value]
    return value


def _summary_for_payload_log(summary: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "request_index",
        "continuation_mode",
        "responses_mode",
        "requested_responses_mode",
        "previous_response_id_present",
        "instructions_present",
        "instructions_chars",
        "tool_choice",
        "parallel_tool_calls",
        "include",
        "input_item_count",
        "approx_input_chars",
        "approx_input_tokens",
        "environment_context_chars",
        "permissions_context_chars",
        "collaboration_context_chars",
        "internal_context_chars",
        "skills_context_chars",
        "mcp_servers_context_chars",
        "operational_memory_context_chars",
        "project_instructions_context_chars",
        "tools_included_count",
        "context_item_hash",
        "context_update_mode",
        "persistent_context_update_mode",
    )
    return {key: summary.get(key) for key in keys if key in summary}


def _is_secret_key(key: str) -> bool:
    normalized = key.replace("-", "_").replace(" ", "_").lower()
    return any(part in normalized for part in SECRET_KEY_PARTS)
