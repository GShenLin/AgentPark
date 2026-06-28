import json
import os

from . import runtime_paths, state_store
from .service_host import HostBoundService
from .node_config_service import read_node_config_strict, write_node_config
from .node_state_machine import parse_node_state
from .shared import (
    _recover_node_config_startup_state,
    _write_json_dict,
    normalize_envelope,
)
from .route_parser import NodeRouteParser
from .node_memory_store import append_node_memory_entry
from .node_memory_store import append_node_tool_call_entry
from .node_memory_store import ensure_node_memory_files
from .node_config_errors import NodeConfigWriteError
from .node_metadata_reader import load_node_instance
from .node_metadata_reader import read_node_ports
from .node_metadata_reader import run_node_on_create


class GraphNodeStore(HostBoundService):
    def _sync_node_config_ports(self, type_id: str, config: dict, graph_id: str, node_instance_id: str) -> None:
        if not isinstance(config, dict) or not config:
            return
        safe_type_id = str(type_id or "").strip()
        if not safe_type_id:
            return
        node = load_node_instance(safe_type_id)
        if node is None:
            return
        context = self._build_node_context(safe_type_id, graph_id, node_instance_id, config)
        input_num, output_num = read_node_ports(node, context)
        config["input_num"] = input_num
        config["output_num"] = output_num

    def _build_node_context(
        self,
        type_id: str,
        graph_id: str,
        node_instance_id: str,
        cfg: dict | None = None,
    ) -> dict:
        context = {
            "graph_id": graph_id,
            "node_instance_id": node_instance_id,
            "node_type_id": str(type_id or "").strip(),
        }
        if isinstance(cfg, dict):
            self._inject_node_config_into_context(context, cfg)
        return context

    def _inject_node_config_into_context(self, context: dict, cfg: dict) -> None:
        if not isinstance(context, dict) or not isinstance(cfg, dict):
            return
        for k, v in cfg.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if k in self.reserved_node_fields:
                continue
            if k not in context:
                context[k] = v

    def _looks_like_tool_call(self, payload: object) -> bool:
        if isinstance(payload, dict) and isinstance(payload.get("parts"), list):
            for part in payload.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip().lower()
                if part_type in {"tool_call", "function_call"}:
                    return True
                if part_type == "structured":
                    data = part.get("data")
                    if isinstance(data, dict) and self._looks_like_tool_call(data):
                        return True
            return False
        if isinstance(payload, list):
            return any(self._looks_like_tool_call(item) for item in payload)
        if not isinstance(payload, dict):
            return False
        role = str(payload.get("role") or "").strip().lower()
        typ = str(payload.get("type") or "").strip().lower()
        if role == "tool":
            return True
        if typ in {"function_call", "tool_call"}:
            return True
        if payload.get("tool_calls") is not None or payload.get("function_call") is not None:
            return True
        parts = payload.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and part.get("functionCall") is not None:
                    return True
        return False

    def _should_skip_propagation(self, message: object) -> bool:
        envelope = normalize_envelope(message, default_role="assistant")
        parts = envelope.get("parts") if isinstance(envelope, dict) else None
        if not isinstance(parts, list) or not parts:
            return True
        return self._looks_like_tool_call(envelope)

    def _node_dir(self, graph_id: str, node_id: str) -> str:
        graph_id = self._sanitize_graph_id(graph_id)
        safe_id = self._sanitize_node_id(node_id)
        return os.path.join(self._graph_dir(graph_id), safe_id)

    def _node_config_path(self, node_id: str, graph_id: str) -> str:
        node_dir = self._node_dir(graph_id, node_id)
        return os.path.join(node_dir, "config.json") if node_dir else ""

    def _node_memory_path(self, node_id: str, graph_id: str) -> str:
        node_dir = self._node_dir(graph_id, node_id)
        return os.path.join(node_dir, "memory.md") if node_dir else ""

    def _node_messages_path(self, node_id: str, graph_id: str) -> str:
        node_dir = self._node_dir(graph_id, node_id)
        return os.path.join(node_dir, "messages.jsonl") if node_dir else ""

    def _ensure_node_memory_file(self, node_id: str, graph_id: str) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        ensure_node_memory_files(
            self._node_memory_path(safe_node_id, safe_graph_id),
            self._node_messages_path(safe_node_id, safe_graph_id),
        )

    def _persist_node_input_default(self, type_id: str, message: object, context: dict | None = None) -> None:
        safe_type_id = str(type_id or "").strip()
        if not safe_type_id:
            return
        node = load_node_instance(safe_type_id)
        persist_input_fn = getattr(node, "_persist_input_default", None) if node is not None else None
        if callable(persist_input_fn):
            persist_input_fn(message, context if isinstance(context, dict) else {})

    def _append_node_memory_entry(self, graph_id: str, node_id: str, role: str, message: object) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        append_node_memory_entry(
            self._node_memory_path(safe_node_id, safe_graph_id),
            self._node_messages_path(safe_node_id, safe_graph_id),
            role,
            message,
        )

    def _append_node_tool_call_entry(self, graph_id: str, node_id: str, event: dict) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        append_node_tool_call_entry(
            self._node_memory_path(safe_node_id, safe_graph_id),
            self._node_messages_path(safe_node_id, safe_graph_id),
            event,
        )

    def _write_node_config(
        self,
        node_id: str,
        type_id: str,
        name: str | None = None,
        graph_id: str | None = None,
        ui: dict | None = None,
    ) -> str | None:
        graph_id = self._sanitize_graph_id(graph_id)
        config_path = self._node_config_path(node_id, graph_id)
        if not config_path:
            return None
        existing: dict = {}
        if os.path.exists(config_path):
            try:
                existing = read_node_config_strict(config_path)
            except NodeConfigWriteError:
                raise
            except Exception as exc:
                raise NodeConfigWriteError(
                    f"Failed to read existing node config {config_path}: {type(exc).__name__}: {exc}"
                ) from exc
        existing_ui = existing.get("ui")
        existing_state = existing.get("state")
        existing_pending = existing.get("pending")
        existing_input_num = NodeRouteParser.parse_port_count(existing.get("input_num"), default=1)
        existing_output_num = NodeRouteParser.parse_port_count(existing.get("output_num"), default=1)
        payload = dict(existing)
        payload.pop("schema", None)
        payload.update(
            {
                "node_id": str(node_id),
                "type_id": str(type_id),
                "name": str(node_id),
                "graph_id": graph_id,
                "state": parse_node_state(existing_state),
                "input_num": existing_input_num,
                "output_num": existing_output_num,
            }
        )
        if isinstance(existing_pending, list) and "pending" not in payload:
            payload["pending"] = existing_pending
        if isinstance(ui, dict):
            payload["ui"] = ui
        elif isinstance(existing_ui, dict) and "ui" not in payload:
            payload["ui"] = existing_ui
        try:
            write_node_config(config_path, payload)
            return config_path
        except Exception as exc:
            raise NodeConfigWriteError(
                f"Failed to write node config {config_path}: {type(exc).__name__}: {exc}"
            ) from exc

    def _try_init_node_config(self, type_id: str, config: dict, graph_id: str, node_instance_id: str) -> None:
        if not isinstance(config, dict) or not config:
            return
        context = self._build_node_context(type_id, graph_id, node_instance_id, config)
        node = load_node_instance(type_id)
        if node is None:
            return

        run_node_on_create(node, config, context)
        config.pop("schema", None)
        self._sync_node_config_ports(type_id, config, graph_id, node_instance_id)

    def _recover_node_runtime_state_on_startup(self) -> dict:
        graphs_dir = runtime_paths._get_graphs_dir()
        summary = {"graphs_woken": 0, "nodes_reset_to_idle": 0, "inflight_requeued": 0}
        if not graphs_dir or not os.path.isdir(graphs_dir):
            return summary

        graphs_to_wake: set[str] = set()
        for graph_entry in os.listdir(graphs_dir):
            graph_dir = os.path.join(graphs_dir, graph_entry)
            if not os.path.isdir(graph_dir):
                continue
            safe_graph_id = self._sanitize_graph_id(graph_entry)
            if not safe_graph_id:
                continue

            for node_entry in os.listdir(graph_dir):
                if node_entry == "agents":
                    continue
                node_dir = os.path.join(graph_dir, node_entry)
                if not os.path.isdir(node_dir):
                    continue
                config_path = os.path.join(node_dir, "config.json")
                if not os.path.exists(config_path):
                    continue
                cfg = state_store._read_json_dict(config_path)
                if not isinstance(cfg, dict) or not cfg:
                    continue

                recovery = _recover_node_config_startup_state(config_path)
                if not isinstance(recovery, dict):
                    continue
                before_state = parse_node_state(recovery.get("before_state"))
                recovered = bool(recovery.get("recovered"))
                if bool(recovery.get("inflight_requeued")):
                    summary["inflight_requeued"] += 1
                if recovered and before_state == "working":
                    summary["nodes_reset_to_idle"] += 1

                if not recovered and before_state != "working":
                    continue

                next_cfg = state_store._read_json_dict(config_path)
                pending = next_cfg.get("pending") if isinstance(next_cfg, dict) else None
                pending_count = len(pending) if isinstance(pending, list) else 0
                next_state = parse_node_state((next_cfg or {}).get("state"))
                if next_state == "idle" and pending_count > 0:
                    graphs_to_wake.add(safe_graph_id)

                self._log_graph_event(
                    safe_graph_id,
                    "startup_node_state_recovered",
                    node_id=self._sanitize_node_id(node_entry),
                    before_state=before_state,
                    after_state=next_state,
                    reason=str(recovery.get("reason") or ""),
                    inflight_requeued=bool(recovery.get("inflight_requeued")),
                    pending_count=pending_count,
                )

        for graph_id in graphs_to_wake:
            self._ensure_graph_runner(graph_id)
            self._wake_graph_runner(graph_id)
        summary["graphs_woken"] = len(graphs_to_wake)
        return summary
