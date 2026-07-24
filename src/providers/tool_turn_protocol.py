from __future__ import annotations

from typing import Any


def openai_tool_call_ids(message: dict[str, Any]) -> list[str]:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    call_ids: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            raise ValueError("Tool call history must contain only objects.")
        call_id = str(call.get("id") or "").strip()
        if not call_id:
            raise ValueError("Tool call history requires a non-empty id.")
        call_ids.append(call_id)
    _require_unique_ids(call_ids, label="tool call")
    return call_ids


def order_tool_result_messages(
    expected_call_ids: list[str],
    result_messages: list[dict[str, Any]],
    *,
    protocol: str,
) -> list[dict[str, Any]]:
    if not expected_call_ids:
        raise ValueError(f"{protocol} tool results require a preceding tool call batch.")
    _require_unique_ids(expected_call_ids, label=f"{protocol} tool call")

    results_by_id: dict[str, dict[str, Any]] = {}
    for message in result_messages:
        if not isinstance(message, dict):
            raise ValueError(f"{protocol} tool result history must contain only objects.")
        call_id = str(message.get("tool_call_id") or "").strip()
        if not call_id:
            raise ValueError(f"{protocol} tool result requires tool_call_id.")
        if call_id in results_by_id:
            raise ValueError(f"{protocol} tool result id is duplicated: {call_id}")
        results_by_id[call_id] = dict(message)

    expected_set = set(expected_call_ids)
    missing = [call_id for call_id in expected_call_ids if call_id not in results_by_id]
    unexpected = [call_id for call_id in results_by_id if call_id not in expected_set]
    if missing or unexpected:
        raise ValueError(
            f"{protocol} tool call/result pairing is incomplete: "
            f"missing={missing}, unexpected={unexpected}."
        )
    return [results_by_id[call_id] for call_id in expected_call_ids]


def prepare_chat_completions_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and order Chat Completions tool turns before serialization."""
    if not isinstance(messages, list):
        raise ValueError("Chat Completions messages must be a list.")

    prepared: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if not isinstance(message, dict):
            raise ValueError("Chat Completions messages must contain only objects.")
        role = str(message.get("role") or "").strip().lower()
        if role == "tool":
            raise ValueError("Chat Completions tool results must immediately follow their assistant tool call turn.")

        prepared.append(dict(message))
        expected_ids = openai_tool_call_ids(message) if role == "assistant" else []
        if not expected_ids:
            index += 1
            continue

        index += 1
        result_messages: list[dict[str, Any]] = []
        while index < len(messages):
            candidate = messages[index]
            if not isinstance(candidate, dict):
                raise ValueError("Chat Completions messages must contain only objects.")
            if str(candidate.get("role") or "").strip().lower() != "tool":
                break
            result_messages.append(candidate)
            index += 1
        prepared.extend(
            order_tool_result_messages(
                expected_ids,
                result_messages,
                protocol="Chat Completions",
            )
        )

    return prepared


def _require_unique_ids(call_ids: list[str], *, label: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for call_id in call_ids:
        if call_id in seen and call_id not in duplicates:
            duplicates.append(call_id)
        seen.add(call_id)
    if duplicates:
        raise ValueError(f"{label} ids must be unique: {duplicates}")


__all__ = [
    "openai_tool_call_ids",
    "order_tool_result_messages",
    "prepare_chat_completions_messages",
]
