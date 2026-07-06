from __future__ import annotations
from typing import Any

from src.tool.tool_json_response import tool_json_payload
from src.user_interaction_store import (
    create_interaction_request,
    normalize_interaction_schema,
    wait_for_interaction_response,
)


def ask_user(
    title: str,
    description: str = "",
    fields: list[dict[str, Any]] | None = None,
    confirm_label: str = "确认",
    timeout_sec: int = 600,
    agent: object | None = None,
) -> str:
    try:
        schema = normalize_interaction_schema(
            title=title,
            description=description,
            fields=fields,
            confirm_label=confirm_label,
        )
        request = create_interaction_request(schema=schema, timeout_sec=timeout_sec, agent=agent)
        completed = wait_for_interaction_response(request["id"], timeout_sec=request["timeout_sec"], agent=agent)
    except Exception as exc:
        return tool_json_payload({"status": "error", "tool": "ask_user", "error": f"{type(exc).__name__}: {exc}"})

    status = str(completed.get("status") or "").strip().lower()
    response = completed.get("response") if isinstance(completed.get("response"), dict) else {}
    payload = {
        "status": "completed" if status == "submitted" else status or "error",
        "tool": "ask_user",
        "request_id": completed.get("id"),
        "values": response.get("values", {}),
        "files": response.get("files", {}),
        "response": response,
    }
    if status != "submitted":
        payload["error"] = str(response.get("error") or f"interaction {status or 'failed'}")
    return tool_json_payload(payload)


ask_user.tool_timeout_seconds = 0


ask_user_declaration = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": (
            "Ask the user for additional information through the WebUI. "
            "Use this when you need text, choices, file attachments, or a custom sandboxed HTML interface from the user before continuing. "
            "The call waits until the user confirms the dialog or the request times out."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Dialog title shown to the user."},
                "description": {"type": "string", "description": "Short explanation of what information is needed."},
                "confirm_label": {"type": "string", "description": "Confirm button label.", "default": "确认"},
                "timeout_sec": {
                    "type": "integer",
                    "description": "Maximum seconds to wait for the user. Default 600, max 3600.",
                    "default": 600,
                },
                "fields": {
                    "type": "array",
                    "description": "UI fields to render. Supported types: text, textarea, select, multiselect, checkbox, file, custom_html.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Stable field id used as the response key."},
                            "type": {
                                "type": "string",
                                "enum": ["text", "textarea", "select", "multiselect", "checkbox", "file", "custom_html"],
                            },
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "placeholder": {"type": "string"},
                            "required": {"type": "boolean", "default": False},
                            "default": {"description": "Default value for text, textarea, select, multiselect, or checkbox."},
                            "options": {
                                "type": "array",
                                "description": "Required for select and multiselect fields.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "value": {"type": "string"},
                                        "label": {"type": "string"},
                                        "disabled": {"type": "boolean"},
                                    },
                                    "required": ["value"],
                                },
                            },
                            "accept": {"type": "string", "description": "Accepted file types for file fields, for example image/*,.pdf."},
                            "multiple": {"type": "boolean", "description": "Allow multiple files for file fields."},
                            "html": {"type": "string", "description": "HTML body for a custom_html field. Rendered inside a sandboxed iframe."},
                            "css": {"type": "string", "description": "Optional CSS for a custom_html field."},
                            "js": {
                                "type": "string",
                                "description": "Optional JavaScript for a custom_html field. Use window.parent.postMessage({ type: 'agentpark-interaction-submit', values: {...} }, '*') to submit.",
                            },
                            "height": {"type": "integer", "description": "Iframe height in pixels for custom_html fields. Min 180, max 900."},
                            "initial_data": {"type": "object", "description": "Initial data exposed to custom_html as window.AGENTPARK_INITIAL_DATA."},
                        },
                        "required": ["id", "type", "label"],
                    },
                },
            },
            "required": ["title"],
        },
    },
}
