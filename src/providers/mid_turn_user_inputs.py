from __future__ import annotations

import json
from typing import Any

from src.providers.agent_runtime_context import get_agent_runtime_context


def consume_mid_turn_user_messages(agent: Any) -> list[dict[str, Any]]:
    callback = get_agent_runtime_context(agent).consume_mid_turn_user_inputs
    if not callable(callback):
        return []
    messages = callback()
    if messages is None:
        return []
    if not isinstance(messages, list):
        raise TypeError("consume_mid_turn_user_inputs must return a list of message dictionaries")
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise TypeError("consume_mid_turn_user_inputs must return message dictionaries")
        role = str(message.get("role") or "").strip().lower()
        if role != "user":
            raise ValueError("mid-turn user input callback may only return user messages")
        normalized.append(dict(message))
    return normalized


def append_mid_turn_user_messages(agent: Any) -> list[dict[str, Any]]:
    messages = consume_mid_turn_user_messages(agent)
    for message in messages:
        agent.Message("user", message.get("content"), persist=False)
    if messages:
        emit = getattr(agent, "_emit_provider_runtime_notice", None)
        if callable(emit):
            emit(
                message=json.dumps({"message_count": len(messages)}, ensure_ascii=False),
                stage="chat_completions_mid_turn_user_input",
            )
    return messages
