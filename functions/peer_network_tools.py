from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.peer_network.contracts import PeerCall
from src.providers.agent_runtime_context import get_agent_runtime_context
from src.tool.tool_json_response import tool_json_error, tool_json_payload


def _request(path: str, payload: dict | None = None) -> dict:
    port = int(os.environ.get("AGENTPARK_WEB_SERVER_PORT", "8766"))
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(f"http://127.0.0.1:{port}{path}", data=body,
                      headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        with urlopen(request, timeout=55) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(8000).decode("utf-8")
        raise RuntimeError(f"Peer API HTTP {exc.code}: {detail}") from exc
    if not isinstance(result, dict):
        raise ValueError("Peer API returned a non-object response.")
    return result


def list_peer_devices() -> str:
    """List paired devices without exposing coordinator credentials or device secrets."""
    try:
        result = _request("/api/peers")
        return tool_json_payload({"status": "success", "local_peer_id": result["peer_id"], "peers": result["peers"]})
    except Exception as exc:
        return tool_json_error(f"Unable to list peer devices: {exc}")


def peer_request(peer_id: str, operation: str, graph_id: str = "", node_id: str = "",
                 text: str = "", message_id: str = "", agent: object | None = None) -> str:
    """Agent RPC uses runtime-owned source attribution and explicit target authorization."""
    try:
        if operation not in {"graphs", "nodes", "conversation", "agent_message"}:
            raise ValueError("Unsupported Agent peer operation.")
        body = {"operation": operation, "graph_id": graph_id, "node_id": node_id,
                "text": text, "message_id": message_id}
        if operation == "agent_message":
            context = get_agent_runtime_context(agent)
            if not context.graph_id or not context.node_id:
                raise ValueError("Sending peer messages requires a running Agent node context.")
            body.update(source_graph_id=context.graph_id, source_node_id=context.node_id)
        call = PeerCall.model_validate(body)
        result = _request(f"/api/peers/{quote(peer_id, safe='')}/call", call.model_dump())
        return tool_json_payload({"status": "success", "result": result})
    except Exception as exc:
        return tool_json_error(f"Peer operation failed: {exc}")


list_peer_devices_declaration = {
    "type": "function", "function": {"name": "list_peer_devices",
        "description": "List paired AgentPark backends and direct-connection states. Permissions listed are the local grants to that peer; the remote device independently authorizes incoming operations.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
}

peer_request_declaration = {
    "type": "function", "function": {"name": "peer_request",
        "description": "View shared graphs, nodes or recent conversation on a paired AgentPark backend, or send an Agent collaboration message. A message receipt only means queued, never task completion. Use a stable unique message_id for a logical message and reuse that ID after an uncertain response. The source device, graph and node are attached so the target Agent can reply with this tool. Do not automatically forward messages in a loop.",
        "parameters": {"type": "object", "properties": {
            "peer_id": {"type": "string"},
            "operation": {"type": "string", "enum": ["graphs", "nodes", "conversation", "agent_message"]},
            "graph_id": {"type": "string"}, "node_id": {"type": "string"}, "text": {"type": "string"},
            "message_id": {"type": "string", "description": "Required for agent_message; unique letters, digits, underscore or hyphen, up to 100 characters."}},
            "required": ["peer_id", "operation"], "additionalProperties": False}},
}
