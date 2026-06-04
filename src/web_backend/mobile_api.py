import os
import socket

from .domain_base import DomainBase
from .shared import HTTPException, _get_runtime_root


LOCAL_PC_ID = "local"


class MobileApiDomain(DomainBase):
    def __init__(self, core, graph_runtime):
        super().__init__(core, graph_runtime)

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
                }
            )
        return result

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
        payload = self.core.node_ops.list_node_instance_configs(safe_graph_id)
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(nodes, list):
            raise HTTPException(status_code=500, detail="invalid node list response")

        result = []
        for item in nodes:
            if not isinstance(item, dict):
                raise HTTPException(status_code=500, detail="invalid node list item")
            node_id = str(item.get("node_id") or "").strip()
            type_id = str(item.get("type_id") or "").strip()
            if not node_id or not type_id:
                raise HTTPException(status_code=500, detail="node list item is missing node_id or type_id")
            result.append(
                {
                    "id": node_id,
                    "name": str(item.get("name") or node_id),
                    "type_id": type_id,
                    "graph_id": safe_graph_id,
                    "state": item.get("state"),
                    "pending_count": item.get("pending_count"),
                    "last_message": item.get("last_message"),
                    "last_run_at": item.get("last_run_at"),
                    "last_runtime_event": item.get("last_runtime_event"),
                    "runtime_tool_calls": item.get("runtime_tool_calls"),
                    "input_num": item.get("input_num"),
                    "output_num": item.get("output_num"),
                }
            )
        return {"pc_id": LOCAL_PC_ID, "graph_id": safe_graph_id, "nodes": result}

    def get_mobile_node_conversation(self, pc_id: str, graph_id: str, node_id: str, max_chars: int = 20000):
        self._require_local_pc(pc_id)
        safe_graph_id = self._require_graph(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if not safe_node_id:
            raise HTTPException(status_code=400, detail="invalid node id")
        return self.core.node_ops.get_node_instance_memory(safe_node_id, max_chars=max_chars, graph_id=safe_graph_id)

    def send_mobile_node_message(self, pc_id: str, graph_id: str, node_id: str, payload: dict):
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
        return self.core.graph_api.emit_graph(
            safe_graph_id,
            {
                "from_id": safe_node_id,
                "payload": message,
                "trace_id": (payload or {}).get("trace_id"),
            },
        )


__all__ = ["MobileApiDomain", "LOCAL_PC_ID"]
