from __future__ import annotations

"""Normalize Seed text calls once, sharing identities across SSE snapshots."""

import copy
from typing import Any

from .contracts import CodexProtocolError
from .doubao_seed_parser import split_seed_calls
from .doubao_seed_tools import SeedToolRegistry


class SeedResponseNormalizer:
    def __init__(self, tools: SeedToolRegistry) -> None:
        self.tools = tools
        self._messages: dict[str, tuple[str, dict[str, Any], list[dict[str, Any]]]] = {}

    def message(self, item: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if item.get("type") != "message" or item.get("role") != "assistant":
            return copy.deepcopy(item), []
        original = message_text(item)
        item_id = str(item.get("id") or "")
        previous = self._messages.get(item_id) if item_id else None
        if previous is not None:
            if previous[0] != original:
                raise CodexProtocolError("Seed message text changed between completed snapshots.")
            return copy.deepcopy(previous[1]), copy.deepcopy(previous[2])
        text, calls = split_seed_calls(original)
        normalized = copy.deepcopy(item)
        if not calls:
            return normalized, []
        if not item_id:
            raise CodexProtocolError("Seed tool-call message requires an item id.")
        # Validate every call before emitting any of them.
        converted = [{**self.tools.convert(call), "status": "completed"} for call in calls]
        remaining = len(text)
        for part in normalized["content"]:
            if part.get("type") in {"output_text", "text"}:
                part["text"] = part["text"][:remaining]
                remaining -= len(part["text"])
        # Ark omits phase; Codex needs commentary for a message preceding tools.
        normalized["phase"] = "commentary"
        self._messages[item_id] = (original, normalized, converted)
        return copy.deepcopy(normalized), copy.deepcopy(converted)

    def response(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = copy.deepcopy(payload)
        if response.get("status") in {"failed", "incomplete", "cancelled", "in_progress", "queued"}:
            return response
        output = response.get("output")
        if not isinstance(output, list):
            raise CodexProtocolError("Seed Responses response requires an output array.")
        normalized: list[dict[str, Any]] = []
        calls: list[dict[str, Any]] = []
        for item in output:
            updated, added = self.message(item)
            normalized.append(updated)
            calls.extend(added)
        if calls:
            if any(item.get("type") in {"function_call", "custom_tool_call"} for item in output):
                raise CodexProtocolError("Seed mixed textual and native tool calls in one response.")
            response["output"] = [*normalized, *calls]
            if "output_text" in response:
                response["output_text"] = "".join(message_text(item) for item in normalized)
        return response


def message_text(item: dict[str, Any]) -> str:
    if item.get("type") != "message":
        return ""
    return "".join(
        part.get("text", "") for part in item.get("content", [])
        if part.get("type") in {"output_text", "text"}
    )
