from __future__ import annotations

import json
from typing import Any


TOOL_ITEM_TYPES = frozenset(
    {
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "collabAgentToolCall",
        "collabToolCall",
        "webSearch",
        "imageView",
        "sleep",
        "imageGeneration",
    }
)


def tool_name(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return "shell_command"
    if item_type == "fileChange":
        return "apply_patch"
    if item_type == "mcpToolCall":
        server = str(item.get("server") or "mcp").strip() or "mcp"
        tool = str(item.get("tool") or "tool").strip() or "tool"
        return f"{server}.{tool}"
    if item_type == "dynamicToolCall":
        namespace = str(item.get("namespace") or "").strip()
        tool = str(item.get("tool") or "tool").strip() or "tool"
        return f"{namespace}.{tool}" if namespace else tool
    if item_type in {"collabAgentToolCall", "collabToolCall"}:
        return f"collaboration.{str(item.get('tool') or 'tool')}"
    return {
        "webSearch": "web_search",
        "imageView": "view_image",
        "sleep": "wait",
        "imageGeneration": "image_generation",
    }.get(item_type, item_type or "codex_tool")


def tool_arguments(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return {"command": str(item.get("command") or ""), "cwd": str(item.get("cwd") or "")}
    if item_type == "fileChange":
        return {"changes": file_change_summary(item.get("changes"))}
    if item_type in {"mcpToolCall", "dynamicToolCall"}:
        arguments = item.get("arguments")
        return dict(arguments) if isinstance(arguments, dict) else {"value": arguments}
    if item_type in {"collabAgentToolCall", "collabToolCall"}:
        return {
            "prompt": item.get("prompt"),
            "model": item.get("model"),
            "receiver_thread_ids": item.get("receiverThreadIds") or item.get("receiverThreadId"),
        }
    if item_type == "webSearch":
        return {"query": str(item.get("query") or ""), "action": item.get("action")}
    if item_type == "imageView":
        return {"path": str(item.get("path") or "")}
    if item_type == "sleep":
        return {"duration_ms": item.get("durationMs")}
    return {}


def tool_result_preview(item: dict[str, Any], *, streamed_output: str = "") -> str:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return str(item.get("aggregatedOutput") or streamed_output or "")
    if item_type == "fileChange":
        return json.dumps(file_change_summary(item.get("changes")), ensure_ascii=False)
    if item_type == "mcpToolCall":
        value = item.get("result")
    elif item_type == "dynamicToolCall":
        value = item.get("contentItems")
    elif item_type in {"collabAgentToolCall", "collabToolCall"}:
        value = item.get("agentsStates") or item.get("agentStatus")
    else:
        value = item.get("action") or item.get("path") or ""
    if isinstance(value, str):
        return value
    return "" if value is None else json.dumps(value, ensure_ascii=False)


def file_change_summary(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    return [
        {"path": str(item.get("path") or ""), "kind": str(item.get("kind") or "")}
        for item in raw
        if isinstance(item, dict)
    ]


def tool_status(raw: Any) -> str:
    status = str(raw or "").strip()
    return {
        "inProgress": "running",
        "completed": "completed",
        "failed": "failed",
        "declined": "declined",
    }.get(status, status or "completed")


def tool_error(item: dict[str, Any]) -> str:
    raw = item.get("error")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return str(raw.get("message") or json.dumps(raw, ensure_ascii=False))
    if tool_status(item.get("status")) in {"failed", "declined"}:
        return f"Codex tool call {item.get('status')}."
    return ""
