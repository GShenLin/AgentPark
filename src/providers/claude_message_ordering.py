from __future__ import annotations

import json
from typing import Any


def normalize_claude_chat_messages(messages: object) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        raise ValueError("Claude chat messages must be a list.")

    ordered_messages: list[dict[str, Any]] = []
    system_contents: list[str] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"Claude chat message[{index}] must be an object.")
        normalized = dict(message)
        role = str(normalized.get("role") or "").strip().lower()
        if role == "system":
            content = normalized.get("content")
            if isinstance(content, str):
                text = content.strip()
            else:
                text = json.dumps(content, ensure_ascii=False).strip() if content is not None else ""
            if text:
                system_contents.append(text)
            continue
        ordered_messages.append(normalized)

    if system_contents:
        ordered_messages.insert(
            0,
            {
                "role": "system",
                "content": "\n\n".join(system_contents),
            }
        )
    return ordered_messages
