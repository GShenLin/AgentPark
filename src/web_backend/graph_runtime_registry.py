import json
import os
import re
import threading
from datetime import datetime
from json import JSONDecodeError

from . import runtime_paths, state_store
from .service_host import HostBoundService
from .shared import envelope_preview


class GraphConfigReadError(RuntimeError):
    pass


class GraphRuntimeRegistry(HostBoundService):
    def _graph_event_log_path(self, graph_id: str) -> str:
        safe_id = self._sanitize_graph_id(graph_id)
        base_dir = self._graph_dir(safe_id)
        return os.path.join(base_dir, "runner.events.jsonl") if base_dir else ""

    def _runtime_log_path(self, graph_id: str) -> str:
        safe_id = self._sanitize_graph_id(graph_id)
        base_dir = self._graph_dir(safe_id)
        return os.path.join(base_dir, "runtime.events.jsonl") if base_dir else ""

    def _log_graph_event(self, graph_id: str, event: str, **fields) -> None:
        safe_id = self._sanitize_graph_id(graph_id)
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": str(event or ""),
            "graph_id": safe_id,
            "pid": os.getpid(),
            "thread": threading.get_ident(),
        }
        for k, v in (fields or {}).items():
            if not isinstance(k, str) or not k.strip():
                continue
            payload[k] = v
        state_store._append_jsonl_line(self._graph_event_log_path(safe_id), payload)
        self.core.graph_events.publish(safe_id, payload)

    def _append_runtime_log(self, graph_id: str, event: str, **fields) -> None:
        safe_id = self._sanitize_graph_id(graph_id)
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": str(event or ""),
            "graph_id": safe_id,
            "pid": os.getpid(),
            "thread": threading.get_ident(),
        }
        for k, v in (fields or {}).items():
            if not isinstance(k, str) or not k.strip() or v is None:
                continue
            payload[k] = v
        state_store._append_jsonl_line(self._runtime_log_path(safe_id), payload)

    def _sanitize_graph_id(self, graph_id: str | None) -> str:
        raw = str(graph_id or "").strip()
        if not raw:
            return self.default_graph_id
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
        return safe or self.default_graph_id

    def _graph_dir(self, graph_id: str) -> str:
        return os.path.join(runtime_paths._get_runtime_root(), "memories", graph_id)

    def _read_graph_config(self, graph_id: str) -> dict:
        safe_id = self._sanitize_graph_id(graph_id)
        graphs_dir = runtime_paths._get_graphs_dir()
        config_path = os.path.join(graphs_dir, safe_id, "config.json")
        if not os.path.exists(config_path):
            if safe_id == "default":
                return {"id": "default", "name": "default", "nodes": [], "output_routes": {}}
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except JSONDecodeError as exc:
            raise GraphConfigReadError(
                f"graph config contains invalid JSON: {config_path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
            ) from exc
        except OSError as exc:
            raise GraphConfigReadError(
                f"failed to read graph config {config_path}: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise GraphConfigReadError(f"graph config must be a JSON object: {config_path}")
        return payload

    @staticmethod
    def _sanitize_node_id(node_id: str | None) -> str:
        raw = str(node_id or "").strip()
        if not raw:
            return "node"
        safe = re.sub(r'[<>:"/\\|?*]', "_", raw)
        safe = safe.strip()
        return safe or "node"

    def _is_safe_subdir(self, root_path: str, target_path: str) -> bool:
        if not root_path or not target_path:
            return False
        try:
            root_real = os.path.normcase(os.path.realpath(root_path))
            target_real = os.path.normcase(os.path.realpath(target_path))
            common = os.path.commonpath([root_real, target_real])
            return common == root_real and target_real != root_real
        except Exception:
            return False
