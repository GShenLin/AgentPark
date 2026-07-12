import os
import socket
import uuid

from .domain_base import DomainBase
from .shared import (
    HTTPException,
    _get_runtime_root,
    _set_node_config_last_message,
    envelope_preview,
    envelope_text,
    normalize_envelope,
)


LOCAL_PC_ID = "local"


class MobileApiDomain(DomainBase):
    def _local_pc_name(self) -> str:
        name = socket.gethostname().strip()
        if not name:
            raise HTTPException(status_code=500, detail="failed to resolve local PC name")
        return name

    def _runtime_instance(self) -> dict:
        runtime_root = _get_runtime_root()
        instance_name = os.path.basename(os.path.normpath(runtime_root))
        if not instance_name:
            raise HTTPException(status_code=500, detail="failed to resolve runtime instance folder")
        return {
            "id": instance_name,
            "name": instance_name,
            "path": runtime_root,
        }

    def _require_local_pc(self, pc_id: str) -> None:
        if str(pc_id or "").strip() != LOCAL_PC_ID:
            raise HTTPException(status_code=404, detail="PC target not found")

    def _list_graph_summaries(self) -> list[dict]:
        instance = self._runtime_instance()
        payload = self.core.graph_api.list_graphs()
        graphs = payload.get("graphs") if isinstance(payload, dict) else None
        if not isinstance(graphs, list):
            raise HTTPException(status_code=500, detail="invalid graph list response")

        result = []
        for item in graphs:
            if not isinstance(item, dict):
                raise HTTPException(status_code=500, detail="invalid graph list item")
            graph_id = str(item.get("id") or "").strip()
            graph_name = str(item.get("name") or "").strip()
            if not graph_id or not graph_name:
                raise HTTPException(status_code=500, detail="graph list item is missing id or name")
            result.append(
                {
                    "id": graph_id,
                    "name": graph_name,
                    "display_name": f"{instance['name']}.{graph_name}",
                    "instance_id": instance["id"],
                    "instance_name": instance["name"],
                    "instance_path": instance["path"],
                    "updated_at": item.get("updated_at"),
                    "readonly": bool(item.get("readonly")),
                    "deletable": bool(item.get("deletable", not item.get("readonly"))),
                    "editable": bool(item.get("editable", True)),
                }
            )
        return result

    def _mobile_node_from_config(self, item: dict, graph_id: str) -> dict:
        node_id = str(item.get("node_id") or "").strip()
        type_id = str(item.get("type_id") or "").strip()
        if not node_id or not type_id:
            raise HTTPException(status_code=500, detail="node list item is missing node_id or type_id")
        return {
            "id": node_id,
            "name": str(item.get("name") or node_id),
            "type_id": type_id,
            "graph_id": graph_id,
            "state": item.get("state"),
            "pending_count": item.get("pending_count"),
            "has_inflight": isinstance(item.get("inflight"), dict),
            "stop_requested": bool(item.get("_stop_requested")),
            "last_message": item.get("last_message"),
            "last_run_at": item.get("last_run_at"),
            "last_runtime_event": item.get("last_runtime_event"),
            "runtime_tool_calls": item.get("runtime_tool_calls"),
            "goal": str(item.get("goal") or ""),
            "goal_state": item.get("goal_state") if isinstance(item.get("goal_state"), dict) else None,
            "input_num": item.get("input_num"),
            "output_num": item.get("output_num"),
        }

    def _list_mobile_nodes_for_graph(self, graph_id: str) -> list[dict]:
        payload = self.core.node_ops.list_node_instance_configs(graph_id)
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(nodes, list):
            raise HTTPException(status_code=500, detail="invalid node list response")

        result = []
        for item in nodes:
            if not isinstance(item, dict):
                raise HTTPException(status_code=500, detail="invalid node list item")
            result.append(self._mobile_node_from_config(item, graph_id))
        return result

    def _mobile_node_snapshot(self, graph_id: str, node_id: str) -> dict:
        for item in self._list_mobile_nodes_for_graph(graph_id):
            item_id = str(item.get("id") or "").strip()
            if item_id == node_id:
                return item
        raise HTTPException(status_code=500, detail="sent node is missing from mobile node snapshot")

    def _mobile_node_conversation_snapshot(self, graph_id: str, node_id: str, history_mode: str = "latest_turn"):
        return self.core.node_ops.get_node_instance_memory(
            node_id,
            max_chars=None,
            graph_id=graph_id,
            messages_limit=None,
            history_mode=history_mode,
        )

    def _require_graph(self, graph_id: str) -> str:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if not safe_graph_id:
            raise HTTPException(status_code=400, detail="invalid graph id")
        if not any(item["id"] == safe_graph_id for item in self._list_graph_summaries()):
            raise HTTPException(status_code=404, detail="graph not found")
        return safe_graph_id

    def list_mobile_pcs(self):
        instance = self._runtime_instance()
        return {
            "pcs": [
                {
                    "id": LOCAL_PC_ID,
                    "name": self._local_pc_name(),
                    "instance_count": 1,
                    "instances": [instance],
                }
            ]
        }

    def list_mobile_graphs(self, pc_id: str):
        self._require_local_pc(pc_id)
        instance = self._runtime_instance()
        return {
            "pc_id": LOCAL_PC_ID,
            "instances": [
                {
                    **instance,
                    "graphs": self._list_graph_summaries(),
                }
            ],
        }

    def list_mobile_nodes(self, pc_id: str, graph_id: str):
        self._require_local_pc(pc_id)
        safe_graph_id = self._require_graph(graph_id)
        return {"pc_id": LOCAL_PC_ID, "graph_id": safe_graph_id, "nodes": self._list_mobile_nodes_for_graph(safe_graph_id)}

    def get_mobile_node_conversation(self, pc_id: str, graph_id: str, node_id: str, history_mode: str = "latest_turn"):
        self._require_local_pc(pc_id)
        safe_graph_id = self._require_graph(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if not safe_node_id:
            raise HTTPException(status_code=400, detail="invalid node id")
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, safe_node_id)
        return self._mobile_node_conversation_snapshot(safe_graph_id, safe_node_id, history_mode=history_mode)

    def delete_mobile_node_message(self, pc_id: str, graph_id: str, node_id: str, message_id: str):
        self._require_local_pc(pc_id)
        safe_graph_id = self._require_graph(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if not safe_node_id:
            raise HTTPException(status_code=400, detail="invalid node id")
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, safe_node_id)
        return self.core.node_ops.delete_node_instance_memory_message(
            safe_node_id,
            message_id,
            graph_id=safe_graph_id,
        )

    def send_mobile_node_message(
        self,
        pc_id: str,
        graph_id: str,
        node_id: str,
        payload: dict,
        history_mode: str = "latest_turn",
    ):
        self._require_local_pc(pc_id)
        safe_graph_id = self._require_graph(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if not safe_node_id:
            raise HTTPException(status_code=400, detail="invalid node id")
        message = (payload or {}).get("payload")
        if message is None:
            message = (payload or {}).get("message")
        if message is None:
            raise HTTPException(status_code=400, detail="message is required")
        message = normalize_envelope(message, default_role="user")
        trace_id = str((payload or {}).get("trace_id") or "").strip() or uuid.uuid4().hex
        text_full = envelope_text(message).strip()
        text_preview = envelope_preview(message)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, safe_node_id)
        result = self.core.node_ops.enqueue_node_instance_pending(
            safe_node_id,
            {
                "payload": message,
                "trace_id": trace_id,
                "depth": 0,
                "visited": [],
                "from": safe_node_id,
                "source": "emit",
            },
            graph_id=safe_graph_id,
        )
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        _set_node_config_last_message(config_path, text_full or text_preview)
        try:
            self.graph_runtime._append_node_memory_entry(safe_graph_id, safe_node_id, "user", message)
        except Exception as exc:
            self.graph_runtime._log_graph_event(
                safe_graph_id,
                "mobile_emit_memory_persistence_error",
                trace_id=trace_id,
                from_id=safe_node_id,
                error=f"{type(exc).__name__}: {exc}",
            )
        self.core.node_live_outputs.publish_event(
            safe_graph_id,
            safe_node_id,
            "node_input",
            {"type": "node_input", "text": text_full or text_preview},
            trace_id=trace_id,
        )
        return {
            "ok": True,
            "queued": True,
            "trace_id": trace_id,
            "pending_count": result.get("pending_count"),
            "node": self._mobile_node_snapshot(safe_graph_id, safe_node_id),
            "conversation": self._mobile_node_conversation_snapshot(
                safe_graph_id,
                safe_node_id,
                history_mode=history_mode,
            ),
        }


__all__ = ["MobileApiDomain", "LOCAL_PC_ID"]
