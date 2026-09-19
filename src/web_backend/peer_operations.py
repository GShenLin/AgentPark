from __future__ import annotations

import asyncio
import hashlib

from fastapi import Request

from src.peer_network.contracts import PeerCall, PeerGrant
from src.peer_network.principal import PeerPrincipal
from src.peer_network.delivery import DeliveryJournal


class PeerOperations:
    """Allowlisted business operations; never dispatch arbitrary HTTP paths or methods."""

    def __init__(self, core, journal: DeliveryJournal):
        self.core = core
        self.journal = journal

    async def __call__(self, grant: PeerGrant, call: PeerCall) -> dict:
        return await asyncio.to_thread(self.execute, grant, call)

    def execute(self, grant: PeerGrant, call: PeerCall) -> dict:
        if call.operation == "board_http":
            raise PermissionError("Board transport requires a cloud browser session.")
        permission = {"graphs": "view", "nodes": "view", "conversation": "view",
                      "message": "control", "control": "control", "agent_message": "collaborate"}[call.operation]
        if not getattr(grant, permission):
            raise PermissionError(f"Device is not authorized for {permission} operations.")
        request = Request({"type": "http", "method": "POST", "path": "/peer", "headers": [],
                           "client": ("peer:" + grant.peer_id, 0),
                           "state": {"peer_principal": PeerPrincipal(grant.peer_id, grant.name)}})
        if call.operation == "graphs":
            payload = self.core.graph_api.list_graphs(request)
            return {"graphs": [{"id": g["id"], "name": g["name"]} for g in payload["graphs"]
                               if g["id"] in grant.graph_ids]}
        if not call.graph_id or call.graph_id not in grant.graph_ids:
            raise PermissionError("Graph is not shared with this device.")
        self.core.graph_api.require_graph_visible(call.graph_id, request)
        if call.operation == "nodes":
            payload = self.core.mobile_api.list_mobile_nodes("local", call.graph_id, request)
            # Do not export provider configuration, filesystem paths or runtime tool arguments.
            fields = {"id", "name", "type_id", "graph_id", "state", "pending_count", "has_inflight", "stop_requested"}
            return {"nodes": [{k: v for k, v in node.items() if k in fields} for node in payload["nodes"]]}
        if not call.node_id:
            raise ValueError("A target node is required.")
        self.core.node_ops.require_node_visible(call.node_id, call.graph_id, request)
        if call.operation == "conversation":
            payload = self.core.node_ops.get_node_instance_memory(call.node_id, graph_id=call.graph_id,
                                                                 max_chars=100000, messages_limit=50, history_mode="recent")
            return {key: payload[key] for key in ("text", "messages", "history_complete", "state", "live_message")}
        if call.operation == "control":
            if call.action != "stop":
                raise ValueError("Only stop is supported by the peer control operation.")
            return self.core.node_ops.control_node_instance(call.node_id, {"action": "stop"}, graph_id=call.graph_id)
        if not call.text.strip() or not call.message_id:
            raise ValueError("Messages require text and a stable message_id.")
        if call.operation == "agent_message" and (not call.source_graph_id or not call.source_node_id):
            raise ValueError("Agent messages require the source graph and node.")
        source = {"peer_id": grant.peer_id, "graph_id": call.source_graph_id, "node_id": call.source_node_id}
        # Source is transport-authenticated at device level. Node attribution is asserted by that device.
        origin = f"AgentPark device {grant.name} ({grant.peer_id})"
        if call.operation == "agent_message":
            origin += f", Agent {call.source_graph_id}/{call.source_node_id}"
        content = f"[Message from {origin}; message_id={call.message_id}]\n{call.text}"
        dedup = hashlib.sha256(f"{grant.peer_id}:{call.graph_id}:{call.node_id}:{call.message_id}".encode()).hexdigest()
        def enqueue():
            result = self.core.node_ops.enqueue_node_instance_pending(
                call.node_id, {"payload": {"role": "user", "content": content}, "trace_id": dedup,
                               "idempotency_key": dedup, "source": "peer_agent" if call.operation == "agent_message" else "peer_user",
                               "from": "peer_" + grant.peer_id[:16]},
                graph_id=call.graph_id, request=request,
            )
            return {"queued": True, "completed": False, "message_id": call.message_id,
                    "duplicate": result["duplicate"], "pending_count": result["pending_count"], "source": source}
        return self.journal.accept(dedup, call.model_dump(), enqueue)
