from __future__ import annotations

import json
from typing import Any

from src.providers.tool_call_execution import parse_openai_tool_call_items
from src.providers.tool_turn_protocol import order_tool_result_messages


def map_messages_to_claude(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Map internal chat history to the strict Claude Messages turn contract."""
    if not isinstance(messages, list):
        raise ValueError("Claude messages must be a list.")

    system_parts: list[str] = []
    conversation: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Claude messages must contain only objects.")
        role = str(message.get("role") or "").strip().lower()
        if role in {"system", "developer"}:
            text = message_content_text(message.get("content")).strip()
            if text:
                system_parts.append(text)
            continue
        conversation.append(message)

    mapped: list[dict[str, Any]] = []
    index = 0
    while index < len(conversation):
        message = conversation[index]
        role = str(message.get("role") or "").strip().lower()
        if role == "tool":
            tool_messages: list[dict[str, Any]] = []
            while index < len(conversation):
                candidate = conversation[index]
                candidate_role = str(candidate.get("role") or "").strip().lower()
                if candidate_role != "tool":
                    break
                tool_messages.append(candidate)
                index += 1
            _append_claude_tool_result_turn(mapped, tool_messages)
            continue
        if role == "assistant":
            _append_turn(mapped, "assistant", assistant_content_blocks(message))
        elif role == "user":
            _append_turn(mapped, "user", user_content_blocks(message.get("content")))
        else:
            raise ValueError(f"Claude does not accept message role: {role or '<empty>'}")
        index += 1

    return "\n\n".join(system_parts), mapped


def assistant_content_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    native_blocks = message.get("_claude_content_blocks")
    if isinstance(native_blocks, list):
        blocks = [
            dict(block)
            for block in native_blocks
            if isinstance(block, dict) and str(block.get("type") or "").strip()
        ]
        if blocks:
            return blocks

    blocks: list[dict[str, Any]] = []
    text = message_content_text(message.get("content")).strip()
    if text:
        blocks.append({"type": "text", "text": text})
    for tool_call in message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []:
        parsed = parse_openai_tool_call_items([tool_call], provider="claude_message_history")
        if not parsed:
            continue
        item = parsed[0]
        blocks.append(
            {
                "type": "tool_use",
                "id": item.call_id,
                "name": item.name,
                "input": item.arguments,
            }
        )
    return blocks


def user_content_blocks(content: object) -> list[dict[str, Any]]:
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type == "text":
                text = str(part.get("text") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
                continue
            if part_type in {"image_url", "input_image"}:
                block = image_part_to_claude(part)
                if block:
                    blocks.append(block)
        return blocks
    text = message_content_text(content)
    return [{"type": "text", "text": text}] if text else []


def message_content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        texts = [
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(item for item in texts if item)
    return json.dumps(content, ensure_ascii=False)


def image_part_to_claude(part: dict[str, Any]) -> dict[str, Any] | None:
    url = ""
    if str(part.get("type") or "").strip().lower() == "input_image":
        url = str(part.get("image_url") or "").strip()
    else:
        image_url = part.get("image_url")
        url = str((image_url or {}).get("url") or "").strip() if isinstance(image_url, dict) else ""
    if not url:
        return None
    if url.startswith("data:") and ";base64," in url:
        header, data = url.split(";base64,", 1)
        media_type = header.removeprefix("data:") or "image/png"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _append_claude_tool_result_turn(
    mapped: list[dict[str, Any]],
    tool_messages: list[dict[str, Any]],
) -> None:
    if not mapped or mapped[-1].get("role") != "assistant":
        raise ValueError("Claude tool_result blocks must immediately follow an assistant tool_use turn.")

    expected_ids = [
        str(block.get("id") or "").strip()
        for block in mapped[-1].get("content", [])
        if isinstance(block, dict) and str(block.get("type") or "").strip().lower() == "tool_use"
    ]
    if not expected_ids or any(not call_id for call_id in expected_ids):
        raise ValueError("Claude tool_result blocks require non-empty tool_use ids in the preceding assistant turn.")

    ordered_messages = order_tool_result_messages(
        expected_ids,
        tool_messages,
        protocol="Claude Messages",
    )
    _append_turn(mapped, "user", [tool_result_block(message) for message in ordered_messages])


def tool_result_block(message: dict[str, Any]) -> dict[str, Any]:
    call_id = str(message.get("tool_call_id") or "").strip()
    if not call_id:
        raise ValueError("Claude tool_result requires tool_call_id.")
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": text,
    }


def _append_turn(mapped: list[dict[str, Any]], role: str, content: list[dict[str, Any]]) -> None:
    if not content:
        return
    if mapped and mapped[-1].get("role") == role:
        mapped[-1]["content"].extend(content)
        return
    mapped.append({"role": role, "content": list(content)})


__all__ = ["map_messages_to_claude"]
