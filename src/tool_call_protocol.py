from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import uuid


@dataclass(frozen=True)
class ToolCallEnvelope:
    name: str
    call_id: str
    arguments: dict[str, Any]
    arguments_json: str
    provider: str
    raw: Any = None


@dataclass(frozen=True)
class ToolCallExecution:
    func_name: str
    call_id: str
    cleaned_result: Any
    image_data: dict[str, Any] | None = None
    status: str = "completed"
    error: str | None = None
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "func_name": self.func_name,
            "call_id": self.call_id,
            "cleaned_result": self.cleaned_result,
            "image_data": self.image_data,
            "status": self.status,
            "error": self.error,
            "diagnostics": list(self.diagnostics),
        }


def build_tool_call_error_execution(
    call: ToolCallEnvelope,
    *,
    status: str,
    error: str,
) -> ToolCallExecution:
    tool_name = call.name if isinstance(call, ToolCallEnvelope) else "tool"
    normalized_status = str(status or "error").strip().lower() or "error"
    error_text = str(error or "").strip()
    return ToolCallExecution(
        func_name=tool_name,
        call_id=call.call_id if isinstance(call, ToolCallEnvelope) else "",
        cleaned_result=ensure_json_text(
            {
                "status": normalized_status,
                "tool": tool_name,
                "error": error_text,
            }
        ),
        image_data=None,
        status=normalized_status,
        error=error_text,
    )


def ensure_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def parse_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"failed to parse tool arguments JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("tool arguments JSON must decode to an object")
        return dict(parsed)
    if arguments is None:
        return {}
    raise ValueError(f"tool arguments must be object or JSON string, got {type(arguments).__name__}")


def build_runtime_call_id(provider: str, name: str, arguments_json: str, raw: Any = None) -> str:
    safe_provider = "".join(ch if ch.isalnum() else "_" for ch in str(provider or "tool").strip().lower()).strip("_")
    return f"{safe_provider or 'tool'}-{uuid.uuid4().hex[:16]}"


def normalize_call_id(raw_call_id: Any, *, provider: str, name: str, arguments_json: str, raw: Any = None) -> str:
    call_id = str(raw_call_id or "").strip()
    if call_id:
        return call_id
    return build_runtime_call_id(provider, name, arguments_json, raw)


def from_openai_tool_call(tool_call: Any, provider: str = "openai") -> ToolCallEnvelope | None:
    if not isinstance(tool_call, dict):
        return None
    function_item = tool_call.get("function")
    if not isinstance(function_item, dict):
        return None
    name = str(function_item.get("name") or "").strip()
    if not name:
        return None
    raw_arguments = function_item.get("arguments")
    arguments_json = ensure_json_text(raw_arguments if raw_arguments is not None else {})
    arguments = parse_arguments(arguments_json)
    call_id = normalize_call_id(
        tool_call.get("id"),
        provider=provider,
        name=name,
        arguments_json=arguments_json,
        raw=tool_call,
    )
    return ToolCallEnvelope(
        name=name,
        call_id=call_id,
        arguments=arguments,
        arguments_json=arguments_json,
        provider=provider,
        raw=tool_call,
    )


def from_responses_function_call(item: Any, provider: str = "responses") -> ToolCallEnvelope | None:
    if not isinstance(item, dict):
        return None
    if str(item.get("type") or "").strip().lower() != "function_call":
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    raw_arguments = item.get("arguments")
    arguments_json = ensure_json_text(raw_arguments if raw_arguments is not None else {})
    arguments = parse_arguments(arguments_json)
    call_id = normalize_call_id(
        item.get("call_id") or item.get("id"),
        provider=provider,
        name=name,
        arguments_json=arguments_json,
        raw=item,
    )
    return ToolCallEnvelope(
        name=name,
        call_id=call_id,
        arguments=arguments,
        arguments_json=arguments_json,
        provider=provider,
        raw=item,
    )


def from_gemini_function_call(function_call: Any, provider: str = "gemini") -> ToolCallEnvelope | None:
    if not isinstance(function_call, dict):
        return None
    name = str(function_call.get("name") or "").strip()
    if not name:
        return None
    raw_arguments = function_call.get("args")
    arguments_json = ensure_json_text(raw_arguments if raw_arguments is not None else {})
    arguments = parse_arguments(raw_arguments)
    return ToolCallEnvelope(
        name=name,
        call_id=normalize_call_id(
            function_call.get("call_id") or function_call.get("id"),
            provider=provider,
            name=name,
            arguments_json=arguments_json,
            raw=function_call,
        ),
        arguments=arguments,
        arguments_json=arguments_json,
        provider=provider,
        raw=function_call,
    )


def to_openai_tool_call(envelope: ToolCallEnvelope) -> dict[str, Any]:
    return {
        "id": envelope.call_id or "",
        "type": "function",
        "function": {
            "name": envelope.name,
            "arguments": envelope.arguments_json,
        },
    }
