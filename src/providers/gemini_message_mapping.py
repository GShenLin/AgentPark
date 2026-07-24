from __future__ import annotations

import base64
import json
from typing import Any

from src.providers.provider_errors import ProviderImageAttachmentError
from src.providers.tool_turn_protocol import order_tool_result_messages


_INTERNAL_CALL_ID = "_agentpark_call_id"


def attach_gemini_call_ids(parts: list[dict[str, Any]], call_ids: list[str]) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    call_index = 0
    for part in parts:
        if not isinstance(part, dict):
            continue
        copied = dict(part)
        if isinstance(copied.get("functionCall"), dict):
            if call_index >= len(call_ids):
                raise ValueError("Gemini function call parts exceed normalized call envelopes.")
            copied[_INTERNAL_CALL_ID] = str(call_ids[call_index])
            call_index += 1
        attached.append(copied)
    if call_index != len(call_ids):
        raise ValueError("Gemini normalized call envelopes exceed function call parts.")
    return attached


def map_messages_to_gemini(messages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(messages, list):
        raise ValueError("Gemini messages must be a list.")

    system_parts: list[dict[str, Any]] = []
    conversation: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Gemini messages must contain only objects.")
        role = str(message.get("role") or "").strip().lower()
        if role in {"system", "developer"}:
            system_parts.extend(_content_parts(message.get("content"), allow_file_image=False))
            continue
        conversation.append(message)

    contents: list[dict[str, Any]] = []
    pending_calls: list[tuple[str, str, str]] = []
    index = 0
    while index < len(conversation):
        message = conversation[index]
        role = str(message.get("role") or "").strip().lower()
        if pending_calls and role != "function":
            raise ValueError("Gemini function responses must immediately follow their model function call turn.")

        if role == "assistant":
            parts = _assistant_parts(message)
            pending_calls = _pending_calls(parts)
            _append_content(contents, "model", [_wire_part(part) for part in parts])
            index += 1
            continue
        if role == "user":
            _append_content(contents, "user", _content_parts(message.get("content"), allow_file_image=True))
            index += 1
            continue
        if role == "function":
            function_messages: list[dict[str, Any]] = []
            while index < len(conversation):
                candidate = conversation[index]
                if str(candidate.get("role") or "").strip().lower() != "function":
                    break
                function_messages.append(candidate)
                index += 1
            expected_ids = [call_id for call_id, _wire_id, _name in pending_calls]
            ordered = order_tool_result_messages(
                expected_ids,
                function_messages,
                protocol="Gemini GenerateContent",
            )
            call_by_id = {call_id: (wire_id, name) for call_id, wire_id, name in pending_calls}
            response_parts = []
            for result in ordered:
                call_id = str(result["tool_call_id"])
                wire_id, expected_name = call_by_id[call_id]
                actual_name = str(result.get("name") or "").strip()
                if actual_name != expected_name:
                    raise ValueError(
                        f"Gemini function response name does not match call {call_id}: "
                        f"expected={expected_name!r}, actual={actual_name!r}."
                    )
                response = {
                    "name": expected_name,
                    "response": build_function_response_content(result.get("content")),
                }
                if wire_id:
                    response["id"] = wire_id
                response_parts.append({"functionResponse": response})
            _append_content(contents, "user", response_parts)
            pending_calls = []
            continue
        raise ValueError(f"Gemini does not accept message role: {role or '<empty>'}")

    if pending_calls:
        raise ValueError("Gemini model function call turn is missing its function response batch.")
    system_instruction = {"parts": system_parts} if system_parts else None
    return system_instruction, contents


def build_function_response_content(content: object) -> dict[str, Any]:
    if not isinstance(content, str):
        return {"result": content}
    text = content.strip()
    if not text or not text.startswith("{"):
        return {"result": content}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"result": content}
    return parsed if isinstance(parsed, dict) else {"result": content}


def _assistant_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    parts = message.get("parts")
    if isinstance(parts, list):
        return [dict(part) for part in parts if isinstance(part, dict)]
    content = message.get("content")
    return [{"text": "" if content is None else str(content)}]


def _pending_calls(parts: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []
    for part in parts:
        function_call = part.get("functionCall")
        if not isinstance(function_call, dict):
            continue
        internal_id = str(part.get(_INTERNAL_CALL_ID) or function_call.get("id") or "").strip()
        wire_id = str(function_call.get("id") or "").strip()
        name = str(function_call.get("name") or "").strip()
        if not internal_id or not name:
            raise ValueError("Gemini function call history requires an internal call id and function name.")
        calls.append((internal_id, wire_id, name))
    return calls


def _wire_part(part: dict[str, Any]) -> dict[str, Any]:
    copied = dict(part)
    copied.pop(_INTERNAL_CALL_ID, None)
    return copied


def _content_parts(content: object, *, allow_file_image: bool) -> list[dict[str, Any]]:
    if isinstance(content, dict) and content.get("type") == "image_data":
        parts: list[dict[str, Any]] = []
        text = str(content.get("text") or "")
        if text:
            parts.append({"text": text})
        parts.append(
            {
                "inline_data": {
                    "mime_type": str(content.get("mime_type") or "image/png"),
                    "data": content.get("data"),
                }
            }
        )
        return parts
    if allow_file_image and isinstance(content, dict) and content.get("type") == "image":
        image_path = str(content.get("path") or "")
        parts = []
        text = str(content.get("text") or "")
        if text:
            parts.append({"text": text})
        try:
            with open(image_path, "rb") as image_file:
                encoded = base64.b64encode(image_file.read()).decode("utf-8")
        except Exception as exc:
            raise ProviderImageAttachmentError(
                f"failed to read image file {image_path}: {type(exc).__name__}: {exc}"
            ) from exc
        parts.append({"inline_data": {"mime_type": "image/png", "data": encoded}})
        return parts
    return [{"text": "" if content is None else str(content)}]


def _append_content(contents: list[dict[str, Any]], role: str, parts: list[dict[str, Any]]) -> None:
    if not parts:
        return
    if contents and contents[-1].get("role") == role:
        contents[-1]["parts"].extend(parts)
        return
    contents.append({"role": role, "parts": list(parts)})


__all__ = [
    "attach_gemini_call_ids",
    "build_function_response_content",
    "map_messages_to_gemini",
]
