from .domain_base import DomainBase
from .shared import *
from .graph_api_storage import GraphApiStorage
from .graph_visibility import GraphVisibilityService
from .node_visibility import NodeVisibilityService
from .graph_runtime_registry import GraphConfigReadError
from .node_state_machine import parse_node_state
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from ..workspace_settings import (
    read_startup_graph_settings,
    save_startup_graph_settings,
)


class GraphApiDomain(DomainBase):
    def _resolve_config_trigger_message(self, type_id: str, cfg: dict, text_full: str) -> object | None:
        safe_type_id = str(type_id or "").strip()
        if text_full:
            return None
        if safe_type_id == "basic_trigger_node":
            trigger_output = cfg.get("OutputText")
            if trigger_output is None:
                trigger_output = cfg.get("output_text")
            if trigger_output is not None:
                return str(trigger_output)
        if safe_type_id == "console_command_node":
            command = str(cfg.get("Command") or "").strip()
            if command:
                return command
        return None

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (GraphVisibilityService(self), NodeVisibilityService(self), GraphApiStorage(self))
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    def get_startup_graph_config(self, request: Request = None):
        cfg = read_startup_graph_settings()
        graph_id = self.graph_runtime._sanitize_graph_id(cfg.get("graph_id") or self.default_graph_id)
        graph_name = str(cfg.get("graph_name") or "").strip() or graph_id
        try:
            self.require_graph_visible(graph_id, request)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            visible_graphs = self.list_graphs(request).get("graphs", [])
            if not visible_graphs:
                raise HTTPException(status_code=404, detail="no public graph found") from exc
            first_graph = visible_graphs[0]
            graph_id = str(first_graph.get("id") or "").strip()
            graph_name = str(first_graph.get("name") or graph_id).strip() or graph_id
        return {"graph_id": graph_id, "graph_name": graph_name}

    def set_startup_graph_config(self, payload: dict, request: Request = None):
        graph_id = str((payload or {}).get("graph_id") or "").strip()
        graph_name = str((payload or {}).get("graph_name") or "").strip()
        if not graph_id:
            raise HTTPException(status_code=400, detail="graph_id is required")

        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        self.require_graph_visible(safe_graph_id, request)
        try:
            save_startup_graph_settings(safe_graph_id, graph_name or safe_graph_id)
        except Exception:
            raise HTTPException(status_code=500, detail="failed to write .cache/startup_graph.json")
        return {"ok": True, "graph_id": safe_graph_id, "graph_name": graph_name or safe_graph_id}

    def _enqueue_external_event_tasks(self, source_graph_id: str, trace_id: str, tasks: list[dict]) -> int:
        safe_source_graph_id = self.graph_runtime._sanitize_graph_id(source_graph_id)
        enqueued = 0
        for task in tasks:
            if not isinstance(task, dict):
                continue
            target_cfg_path = str(task.get("target_cfg_path") or "").strip()
            if not target_cfg_path:
                continue
            target_graph_id = self.graph_runtime._sanitize_graph_id(task.get("target_graph_id") or safe_source_graph_id)
            from_node = str(task.get("from_node") or "__external_event__").strip() or "__external_event__"
            route_output_index = NodeRouteParser.parse_port_index(task.get("route_output_index"))
            if route_output_index is None:
                route_output_index = 0
            to_input_index = NodeRouteParser.parse_port_index(task.get("to_input_index"))
            if to_input_index is None:
                to_input_index = 0
            next_depth = int(task.get("next_depth") or 0)
            route_payload = normalize_envelope(task.get("route_payload"), default_role="assistant")
            next_visited_raw = task.get("next_visited")
            next_visited = [str(v) for v in next_visited_raw if v is not None][-50:] if isinstance(next_visited_raw, list) else []

            next_item = {
                "payload": route_payload,
                "trace_id": trace_id,
                "depth": next_depth,
                "visited": next_visited,
                "from": from_node,
                "from_output_index": route_output_index,
                "to_input_index": to_input_index,
                "source": "event_dispatch_external",
                "_runtime_owner_id": getattr(self.core, "runtime_owner_id", ""),
            }
            link_id = str(task.get("link_id") or "").strip()
            if link_id:
                next_item["link_id"] = link_id

            _append_node_pending(target_cfg_path, next_item)
            self.graph_runtime._ensure_graph_runner(target_graph_id)
            self.graph_runtime._wake_graph_runner(target_graph_id)
            enqueued += 1
        return enqueued

    def emit_event_by_key(self, payload: dict):
        event_key = str((payload or {}).get("event_key") or "").strip()
        if not event_key:
            raise HTTPException(status_code=400, detail="event_key is required")

        event_payload = (payload or {}).get("payload")
        if event_payload is None:
            event_payload = (payload or {}).get("message")
        if event_payload is None:
            event_payload = (payload or {}).get("input")
        event_payload = normalize_envelope(event_payload, default_role="assistant")

        source_graph_id = self.graph_runtime._sanitize_graph_id((payload or {}).get("graph_id") or self.default_graph_id)
        trace_id = str((payload or {}).get("trace_id") or "").strip() or uuid.uuid4().hex
        next_visited = []
        try:
            tasks = self.graph_runtime._collect_event_dispatch_tasks(
                source_graph_id=source_graph_id,
                source_node_id="__external_event__",
                event_key=event_key,
                route_payload=event_payload,
                trace_id=trace_id,
                next_visited=next_visited,
            )
        except GraphConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        if not tasks:
            self.graph_runtime._log_graph_event(
                source_graph_id,
                "external_event_emit_no_target",
                trace_id=trace_id,
                event_key=event_key,
                payload_preview=_preview_text(envelope_preview(event_payload)),
            )
            return {"ok": True, "queued": 0, "trace_id": trace_id, "event_key": event_key}

        enqueued = self._enqueue_external_event_tasks(source_graph_id, trace_id, tasks)
        self.graph_runtime._log_graph_event(
            source_graph_id,
            "external_event_emit_enqueued",
            trace_id=trace_id,
            event_key=event_key,
            payload_preview=_preview_text(envelope_preview(event_payload)),
            queued=enqueued,
        )
        return {"ok": True, "queued": enqueued, "trace_id": trace_id, "event_key": event_key}

    def notify_ue_build_success(self, payload: dict):
        event_payload = (payload or {}).get("payload")
        if event_payload is None:
            event_payload = (payload or {}).get("message")
        if event_payload is None:
            project_name = str((payload or {}).get("project_name") or "").strip()
            target_name = str((payload or {}).get("target_name") or "").strip()
            target_platform = str((payload or {}).get("target_platform") or "").strip()
            target_configuration = str((payload or {}).get("target_configuration") or "").strip()
            timestamp = str((payload or {}).get("timestamp") or "").strip()
            event_payload = (
                f"[UE Build Success] project={project_name} target={target_name} "
                f"platform={target_platform} config={target_configuration} ts={timestamp}"
            )

        forwarded_payload = {
            "event_key": str((payload or {}).get("event_key") or "UE_Buid_Success"),
            "payload": event_payload,
            "graph_id": (payload or {}).get("graph_id"),
            "trace_id": (payload or {}).get("trace_id"),
        }
        return self.emit_event_by_key(forwarded_payload)

    def stop_node_run(self, run_id: str, request: Request = None):
        run = self.node_runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        graph_id = str(run.get("graph_id") or "").strip()
        node_instance_id = str(run.get("node_instance_id") or "").strip()
        if graph_id and node_instance_id:
            self.core.node_ops.require_node_visible(node_instance_id, graph_id, request)
        if run["status"] == "running":
            try:
                run["process"].terminate()
                run["process"].join(timeout=0.2)
            except Exception:
                pass
            run["status"] = "stopped"
            cfg_path = run.get("node_config_path")
            if isinstance(cfg_path, str) and cfg_path:
                _transition_node_config_to_idle(cfg_path)
        return {"status": run["status"]}

    def start_graph_runner(self, graph_id: str, request: Request = None):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        self.require_graph_visible(safe_id, request)
        self.graph_runtime._ensure_graph_runner(safe_id)
        self.graph_runtime._log_graph_event(safe_id, "runner_start_api")
        return {"ok": True, "graph_id": safe_id}

    def get_graph_runner_status(self, graph_id: str, request: Request = None):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        self.require_graph_visible(safe_id, request)
        return self.graph_runtime._runner_status(safe_id)

    def stream_app_events(self, request: Request = None):
        def encode_event(item: dict) -> str:
            return f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        def events():
            last_version = self.core.graph_events.get_global_version()
            yield encode_event({"event": "stream_snapshot", "stream_snapshot": True, "global_version": last_version})
            while True:
                item = self.core.graph_events.wait_for_global_change(last_version, timeout=15.0)
                if not isinstance(item, dict):
                    yield ": keep-alive\n\n"
                    continue
                last_version = int(item.get("global_version") or last_version)
                if str(item.get("event") or "").strip() == "stream_gap":
                    yield encode_event(item)
                    continue
                graph_id = self.graph_runtime._sanitize_graph_id(item.get("graph_id") or self.default_graph_id)
                try:
                    self.require_graph_visible(graph_id, request)
                    if str(item.get("event") or "").strip() == "node_live":
                        node_id = str(item.get("node_instance_id") or item.get("node_id") or "").strip()
                        self.core.node_ops.require_node_visible(node_id, graph_id, request)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        continue
                    raise
                payload = self.sanitize_graph_event_for_request(graph_id, item, request)
                payload["graph_id"] = graph_id
                payload["global_version"] = last_version
                yield encode_event(payload)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @staticmethod
    def retire_legacy_event_stream():
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    def emit_graph(self, graph_id: str, payload: dict, request: Request = None):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        self.require_graph_visible(safe_graph_id, request)
        trace_id = (payload or {}).get("trace_id")
        if not isinstance(trace_id, str) or not trace_id.strip():
            trace_id = uuid.uuid4().hex
        trace_id = trace_id.strip()
        from_id = (payload or {}).get("from_id")
        if from_id is None:
            from_id = (payload or {}).get("from")
        message = (payload or {}).get("payload")
        if message is None:
            message = (payload or {}).get("input")
        if not isinstance(from_id, str) or not from_id.strip():
            raise HTTPException(status_code=400, detail="from_id is required")
        if message is None:
            raise HTTPException(status_code=400, detail="payload is required")
        message = normalize_envelope(message, default_role="user")
        message["trace_id"] = trace_id
        text_full = envelope_text(message).strip()
        text_preview = envelope_preview(message)

        safe_from_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, from_id)
        self.core.node_ops.require_node_visible(safe_from_id, safe_graph_id, request)
        config_path = self.graph_runtime._node_config_path(safe_from_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")

        cfg = _read_json_dict(config_path)
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        type_id = str(cfg.get("type_id") or "").strip()
        config_trigger_message = self._resolve_config_trigger_message(type_id, cfg, text_full)
        if config_trigger_message is not None:
            message = build_text_envelope(str(config_trigger_message), role="user")
            text_full = envelope_text(message).strip()
            text_preview = envelope_preview(message)

        state = parse_node_state(cfg.get("state"))
        if state == "stop":
            self.graph_runtime._log_graph_event(
                safe_graph_id,
                "emit_rejected",
                trace_id=trace_id,
                from_id=safe_from_id,
                reason="node_stopped",
            )
            raise HTTPException(status_code=409, detail="node is stopped")

        item = {
            "payload": message,
            "depth": 0,
            "visited": [],
            "trace_id": trace_id,
            "request_id": trace_id,
            "from": safe_from_id,
            "source": "emit",
            "_runtime_owner_id": getattr(self.core, "runtime_owner_id", ""),
        }
        _set_node_config_last_message(config_path, text_full or text_preview)
        _append_node_pending(config_path, item)
        self.graph_runtime._ensure_graph_runner(safe_graph_id)
        # Write the user message to node memory so the Memory panel reflects it immediately.
        try:
            self.graph_runtime._append_node_memory_entry(safe_graph_id, safe_from_id, 'user', message)
        except Exception as exc:
            self.graph_runtime._log_graph_event(
                safe_graph_id,
                'emit_memory_persistence_error',
                trace_id=trace_id,
                from_id=safe_from_id,
                error=f'{type(exc).__name__}: {exc}',
            )
        # Publish a live event so the SSE stream triggers a memory refresh in the frontend.
        self.core.node_live_outputs.publish_event(
            safe_graph_id,
            safe_from_id,
            'node_input',
            {'type': 'node_input', 'text': text_full or text_preview},
            trace_id=trace_id,
        )
        self.graph_runtime._wake_graph_runner(safe_graph_id)
        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "emit_enqueued",
            trace_id=trace_id,
            from_id=safe_from_id,
            input_preview=_preview_text(text_preview),
        )
        return {"ok": True, "queued": True, "trace_id": trace_id, "request_id": trace_id}

__all__ = ["GraphApiDomain"]
