"""Public conversation projection for a live voice call (never provider metadata)."""
from fastapi import HTTPException

from .node_memory_store import load_recent_node_memory_records


def voice_context_records(runtime, node_id: str, graph_id: str, *, limit=None) -> list[dict]:
    return load_recent_node_memory_records(
        runtime._node_memory_path(node_id, graph_id),
        runtime._node_messages_path(node_id, graph_id),
        limit=limit, roles={"user", "assistant"},
    )


def context_cursor(runtime, node_id: str, graph_id: str) -> str:
    records = voice_context_records(runtime, node_id, graph_id, limit=1)
    return records[-1]["id"] if records else ""


def context_updates(runtime, node_id: str, graph_id: str, after: str) -> dict:
    if context_cursor(runtime, node_id, graph_id) == after:
        return {"messages": [], "cursor": after}
    # The memory store includes archived records and serializes against writers.
    records = voice_context_records(runtime, node_id, graph_id)
    start = 0
    if after:
        index = next((i for i, record in enumerate(records) if record["id"] == after), None)
        if index is None:
            raise HTTPException(409, "聊天记录已被清空或修改，无法继续原同步位置，请重新拨号。")
        start = index + 1
    messages = []
    for record in records[start:start + 32]:
        parts = []
        for part in record["parts"]:
            if part["type"] == "text":
                parts.append({"type": "text", "text": part["text"]})
            elif part["type"] == "resource":
                resource = part["resource"]
                parts.append({"type": "resource", "resource": {
                    key: resource[key] for key in ("uri", "kind", "name", "mime") if key in resource
                }})
        messages.append({"id": record["id"], "role": record["role"], "parts": parts})
    return {"messages": messages, "cursor": messages[-1]["id"] if messages else after}
