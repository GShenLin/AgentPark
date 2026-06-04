import os
import uuid

from .route_parser import NodeRouteParser
from .service_host import HostBoundService
from .shared import (
    HTTPException,
    _append_node_pending,
    _pop_node_pending,
    _preview_text,
    _read_json_dict,
    envelope_preview,
    normalize_envelope,
)


class NodeInstanceQueue(HostBoundService):
    def enqueue_node_instance_pending(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        message = (payload or {}).get("payload")
        if message is None:
            raise HTTPException(status_code=400, detail="payload is required")
        message = normalize_envelope(message, default_role="user")
        trace_id = str((payload or {}).get("trace_id") or "").strip() or uuid.uuid4().hex
        item = {
            "payload": message,
            "depth": int((payload or {}).get("depth") or 0) if isinstance((payload or {}).get("depth"), int) else 0,
            "visited": [str(v) for v in ((payload or {}).get("visited") or []) if v] if isinstance((payload or {}).get("visited"), list) else [],
            "trace_id": trace_id,
            "from_output_index": NodeRouteParser.parse_port_index((payload or {}).get("from_output_index")) or 0,
            "to_input_index": NodeRouteParser.parse_port_index((payload or {}).get("to_input_index")) or 0,
        }
        if isinstance((payload or {}).get("link_id"), str) and str((payload or {}).get("link_id")).strip():
            item["link_id"] = str((payload or {}).get("link_id")).strip()
        if isinstance((payload or {}).get("from"), str) and str((payload or {}).get("from")).strip():
            item["from"] = self.graph_runtime._sanitize_node_id((payload or {}).get("from"))
        if isinstance((payload or {}).get("source"), str) and str((payload or {}).get("source")).strip():
            item["source"] = str((payload or {}).get("source")).strip()
        _append_node_pending(config_path, item)
        cfg = _read_json_dict(config_path)
        pending = cfg.get("pending")
        pending_count = len(pending) if isinstance(pending, list) else 0
        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "pending_enqueue_api",
            trace_id=trace_id,
            node_id=safe_node_id,
            depth=item.get("depth"),
            link_id=item.get("link_id"),
            from_node=item.get("from"),
            from_output_index=item.get("from_output_index"),
            to_input_index=item.get("to_input_index"),
            source=item.get("source"),
            pending_count=pending_count,
            payload_preview=_preview_text(envelope_preview(message)),
        )
        return {"ok": True, "pending_count": pending_count}

    def pop_node_instance_pending(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        return {"ok": True, "item": _pop_node_pending(config_path)}
