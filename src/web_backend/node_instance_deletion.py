import os

from . import runtime_paths
from .node_deletion import NodeDeletionBlocked
from .node_deletion import delete_node_directory
from .service_host import HostBoundService
from .shared import HTTPException


class NodeInstanceDeletion(HostBoundService):
    def delete_node_instance(self, node_id: str, graph_id: str = "", wait_timeout_seconds: float = 10.0):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        node_dir = self.graph_runtime._node_dir(safe_graph_id, safe_node_id)
        memory_root = os.path.join(runtime_paths._get_runtime_root(), "memories")
        try:
            result = delete_node_directory(
                core=self.core,
                graph_runtime=self.graph_runtime,
                graph_id=safe_graph_id,
                node_id=safe_node_id,
                node_dir=node_dir,
                memory_root=memory_root,
                wait_timeout_seconds=wait_timeout_seconds,
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="node instance not found")
        except NodeDeletionBlocked as exc:
            raise HTTPException(status_code=409, detail=f"node deletion is blocked: {str(exc)}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to delete node instance: {str(exc)}")
        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "node_deleted",
            node_id=safe_node_id,
            active_cancelled=result.active_cancelled,
            stopped_runs=result.stopped_runs,
            cleared_pending=result.cleared_pending,
            cleared_inflight=result.cleared_inflight,
        )
        return {"ok": True, "node_id": safe_node_id, "graph_id": safe_graph_id, **result.to_payload()}
