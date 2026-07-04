import os
import socket
import threading
import uuid
from datetime import datetime

from src.cli_commands.chat import _run_one_turn, resolve_chat_target

from .domain_base import DomainBase
from .node_config_service import node_config_service
from .shared import (
    HTTPException,
    _get_runtime_root,
    _set_node_config_last_message,
    _touch_node_config_last_run_at,
    envelope_preview,
    envelope_text,
    normalize_envelope,
)


LOCAL_PC_ID = "local"
COMPANION_GRAPH_ID = "companion"
COMPANION_NODE_ID = "companion"


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

    def _companion_config_path(self) -> str:
        return os.path.join(self.graph_runtime._graph_dir(COMPANION_GRAPH_ID), "config.json")

    def _is_companion_target(self, graph_id: str, node_id: str = "") -> bool:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if safe_graph_id != COMPANION_GRAPH_ID:
            return False
        if not node_id:
            return True
        return self.graph_runtime._sanitize_node_id(node_id) == COMPANION_NODE_ID

    def _companion_node_paths(self) -> tuple[str, str, str]:
        config_path = self._companion_config_path()
        node_dir = os.path.dirname(config_path)
        return config_path, os.path.join(node_dir, "memory.md"), os.path.join(node_dir, "messages.jsonl")

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
                    "readonly": graph_id == COMPANION_GRAPH_ID,
                }
            )
        if not any(item.get("id") == COMPANION_GRAPH_ID for item in result):
            companion = self._companion_graph_summary(instance)
            if companion:
                result.append(companion)
        return result

    def _companion_graph_summary(self, instance: dict) -> dict | None:
        config_path = self._companion_config_path()
        if not os.path.exists(config_path):
            return None
        name = "Companion"
        try:
            cfg = node_config_service.read_strict(config_path)
            if cfg.get("name"):
                name = str(cfg.get("name"))
        except Exception:
            pass
        updated_at = None
        try:
            updated_at = datetime.fromtimestamp(os.path.getmtime(config_path)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            updated_at = None
        return {
            "id": COMPANION_GRAPH_ID,
            "name": name,
            "display_name": f"{instance['name']}.{name}",
            "instance_id": instance["id"],
            "instance_name": instance["name"],
            "instance_path": instance["path"],
            "updated_at": updated_at,
            "readonly": True,
        }

    def _list_companion_nodes(self) -> list[dict]:
        config_path = self._companion_config_path()
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="companion config not found")
        try:
            cfg = node_config_service.read_strict(config_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return [
            {
                "id": COMPANION_NODE_ID,
                "name": str(cfg.get("name") or "Companion"),
                "type_id": str(cfg.get("type_id") or "agent_node"),
                "graph_id": COMPANION_GRAPH_ID,
                "state": "idle",
                "pending_count": 0,
                "last_message": str(cfg.get("last_message") or ""),
                "last_run_at": cfg.get("last_run_at"),
                "last_runtime_event": cfg.get("last_runtime_event"),
                "runtime_tool_calls": cfg.get("runtime_tool_calls"),
                "input_num": 1,
                "output_num": 1,
                "readonly": True,
            }
        ]

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
        if self._is_companion_target(safe_graph_id):
            return {"pc_id": LOCAL_PC_ID, "graph_id": safe_graph_id, "nodes": self._list_companion_nodes()}
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
        if self._is_companion_target(safe_graph_id, safe_node_id):
            config_path, memory_path, messages_path = self._companion_node_paths()
            if not os.path.exists(config_path):
                raise HTTPException(status_code=404, detail="companion config not found")
            return self.core.node_ops.get_node_instance_memory_from_paths(
                config_path,
                memory_path,
                messages_path,
                safe_graph_id,
                safe_node_id,
                max_chars=max_chars,
            )
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, safe_node_id)
        return self.core.node_ops.get_node_instance_memory(safe_node_id, max_chars=max_chars, graph_id=safe_graph_id)

    def delete_mobile_node_message(self, pc_id: str, graph_id: str, node_id: str, message_id: str):
        self._require_local_pc(pc_id)
        safe_graph_id = self._require_graph(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if not safe_node_id:
            raise HTTPException(status_code=400, detail="invalid node id")
        if self._is_companion_target(safe_graph_id, safe_node_id):
            config_path, memory_path, messages_path = self._companion_node_paths()
            if not os.path.exists(config_path):
                raise HTTPException(status_code=404, detail="companion config not found")
            return self.core.node_ops.delete_node_instance_memory_message_from_paths(
                config_path,
                memory_path,
                messages_path,
                safe_graph_id,
                safe_node_id,
                message_id,
            )
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, safe_node_id)
        return self.core.node_ops.delete_node_instance_memory_message(
            safe_node_id,
            message_id,
            graph_id=safe_graph_id,
        )

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
        message = normalize_envelope(message, default_role="user")
        trace_id = str((payload or {}).get("trace_id") or "").strip() or uuid.uuid4().hex
        text_full = envelope_text(message).strip()
        text_preview = envelope_preview(message)
        if self._is_companion_target(safe_graph_id, safe_node_id):
            prompt = text_full or text_preview
            if not prompt:
                raise HTTPException(status_code=400, detail="message text is required")
            config_path = self._companion_config_path()
            if not os.path.exists(config_path):
                raise HTTPException(status_code=404, detail="companion config not found")
            self.core.node_live_outputs.publish_event(
                safe_graph_id,
                safe_node_id,
                "node_input",
                {"type": "node_input", "text": prompt},
                trace_id=trace_id,
            )
            th = threading.Thread(
                target=self._run_companion_turn_background,
                args=(config_path, prompt, trace_id),
                daemon=True,
                name=f"mobile-companion-turn-{trace_id[:8]}",
            )
            th.start()
            return {"ok": True, "queued": True, "trace_id": trace_id, "pending_count": 0}
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
        return {"ok": True, "queued": True, "trace_id": trace_id, "pending_count": result.get("pending_count")}

    def _run_companion_turn_background(self, config_path: str, prompt: str, trace_id: str) -> None:
        graph_id = COMPANION_GRAPH_ID
        node_id = COMPANION_NODE_ID

        def publish_stream(payload: dict) -> None:
            if not isinstance(payload, dict):
                return
            text = str(payload.get("text") or "")
            event_type = str(payload.get("type") or "").strip()
            if text:
                self.core.node_live_outputs.update(graph_id, node_id, text, trace_id=trace_id)
            if event_type:
                self.core.node_live_outputs.publish_event(graph_id, node_id, event_type, payload, trace_id=trace_id)

        try:
            target = resolve_chat_target(config_path)
            _set_node_config_last_message(config_path, prompt)
            result = _run_one_turn(target, prompt, print_stream=False, stream_handler=publish_stream)
            response = str((result or {}).get("response") or "")
            _set_node_config_last_message(config_path, response or prompt)
            _touch_node_config_last_run_at(config_path)
            self.core.node_live_outputs.publish_completion_event(
                graph_id,
                node_id,
                "node_message_done",
                {"type": "node_message_done", "text": response},
                trace_id=trace_id,
            )
            self.graph_runtime._log_graph_event(
                graph_id,
                "node_message_done",
                trace_id=trace_id,
                node_id=node_id,
                node_instance_id=node_id,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            try:
                _set_node_config_last_message(config_path, message)
            except Exception:
                pass
            self.core.node_live_outputs.publish_event(
                graph_id,
                node_id,
                "node_error",
                {"type": "node_error", "error": message},
                trace_id=trace_id,
            )
            self.graph_runtime._log_graph_event(
                graph_id,
                "node_error",
                trace_id=trace_id,
                node_id=node_id,
                node_instance_id=node_id,
                error=message,
            )
        finally:
            self.core.node_live_outputs.clear(graph_id, node_id)


__all__ = ["MobileApiDomain", "LOCAL_PC_ID"]
