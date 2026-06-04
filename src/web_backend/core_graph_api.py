from .domain_base import DomainBase
from .shared import *
from ..workspace_settings import (
    load_workspace_settings,
    read_startup_graph_settings,
    save_workspace_settings,
)


class GraphApiDomain(DomainBase):
    def __init__(self, core, graph_runtime):
        super().__init__(core, graph_runtime)

    def _sanitize_graph_payload_for_storage(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        graph = dict(payload)
        graph.pop("nodes", None)
        return graph

    def get_startup_graph_config(self):
        cfg = read_startup_graph_settings()
        graph_id = self.graph_runtime._sanitize_graph_id(cfg.get("graph_id") or self.default_graph_id)
        graph_name = str(cfg.get("graph_name") or "").strip() or graph_id
        return {"graph_id": graph_id, "graph_name": graph_name}

    def set_startup_graph_config(self, payload: dict):
        graph_id = str((payload or {}).get("graph_id") or "").strip()
        graph_name = str((payload or {}).get("graph_name") or "").strip()
        if not graph_id:
            raise HTTPException(status_code=400, detail="graph_id is required")

        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        cfg = load_workspace_settings()
        cfg["startup_graph_id"] = safe_graph_id
        cfg["startup_graph_name"] = graph_name or safe_graph_id
        try:
            save_workspace_settings(cfg)
        except Exception:
            raise HTTPException(status_code=500, detail="failed to write config/config.json")
        return {"ok": True, "graph_id": safe_graph_id, "graph_name": cfg.get("startup_graph_name")}

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
        tasks = self.graph_runtime._collect_event_dispatch_tasks(
            source_graph_id=source_graph_id,
            source_node_id="__external_event__",
            event_key=event_key,
            route_payload=event_payload,
            trace_id=trace_id,
            next_visited=next_visited,
        )

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

    def stop_node_run(self, run_id: str):
        run = self.node_runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
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

    def start_graph_runner(self, graph_id: str):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        self.graph_runtime._ensure_graph_runner(safe_id)
        self.graph_runtime._log_graph_event(safe_id, "runner_start_api")
        return {"ok": True, "graph_id": safe_id}

    def get_graph_runner_status(self, graph_id: str):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        with self.graph_runners_lock:
            existing = self.graph_runners.get(safe_id)
            threads = existing.get("threads") if isinstance(existing, dict) else None
            worker_count = existing.get("worker_count") if isinstance(existing, dict) else None
            if not isinstance(threads, list):
                legacy_thread = existing.get("thread") if isinstance(existing, dict) else None
                threads = [legacy_thread] if isinstance(legacy_thread, threading.Thread) else []
        alive_threads = [th for th in threads if isinstance(th, threading.Thread) and th.is_alive()]
        running = len(alive_threads) > 0
        return {
            "graph_id": safe_id,
            "running": running,
            "workers": len(alive_threads),
            "worker_count": int(worker_count) if isinstance(worker_count, int) else len(threads),
        }

    def emit_graph(self, graph_id: str, payload: dict):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
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
        text_full = envelope_text(message).strip()
        text_preview = envelope_preview(message)

        safe_from_id = self.graph_runtime._sanitize_node_id(from_id)
        config_path = self.graph_runtime._node_config_path(safe_from_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")

        cfg = _read_json_dict(config_path)
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        type_id = str(cfg.get("type_id") or "").strip()
        if type_id == "basic_trigger_node" and not text_full:
            trigger_output = cfg.get("OutputText")
            if trigger_output is None:
                trigger_output = cfg.get("output_text")
            if trigger_output is not None:
                message = build_text_envelope(str(trigger_output), role="user")
                text_full = envelope_text(message).strip()
                text_preview = envelope_preview(message)

        state = _parse_node_state(cfg.get("state"))
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
            "from": safe_from_id,
            "source": "emit",
        }
        _set_node_config_last_message(config_path, text_full or text_preview)
        _append_node_pending(config_path, item)
        self.graph_runtime._ensure_graph_runner(safe_graph_id)
        self.graph_runtime._wake_graph_runner(safe_graph_id)
        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "emit_enqueued",
            trace_id=trace_id,
            from_id=safe_from_id,
            input_preview=_preview_text(text_preview),
        )
        return {"ok": True, "queued": True, "trace_id": trace_id}

    def list_graphs(self):
        graphs_dir = _get_graphs_dir()
        graphs = []
        if not os.path.isdir(graphs_dir):
            graphs.append({"id": "default", "name": "default", "updated_at": None})
            return {"graphs": graphs}
        default_config = os.path.join(graphs_dir, "default", "config.json")
        default_updated = None
        default_name = "default"
        if os.path.exists(default_config):
            try:
                default_updated = datetime.fromtimestamp(os.path.getmtime(default_config)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                default_updated = None
            try:
                with open(default_config, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict) and payload.get("name"):
                    default_name = str(payload.get("name"))
            except Exception:
                pass
        graphs.append({"id": "default", "name": default_name, "updated_at": default_updated})
        for entry in os.listdir(graphs_dir):
            if entry == "agents":
                continue
            if entry == "default":
                continue
            graph_dir = os.path.join(graphs_dir, entry)
            if not os.path.isdir(graph_dir):
                continue
            config_path = os.path.join(graph_dir, "config.json")
            if not os.path.exists(config_path):
                continue
            name = entry
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    if isinstance(payload, dict) and payload.get("name"):
                        name = str(payload.get("name"))
                except Exception:
                    pass
            updated_at = None
            try:
                updated_at = datetime.fromtimestamp(os.path.getmtime(config_path)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                updated_at = None
            graphs.append({"id": entry, "name": name, "updated_at": updated_at})
        graphs.sort(key=lambda item: item["name"].lower())
        return {"graphs": graphs}

    def get_graph(self, graph_id: str):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if not safe_id:
            raise HTTPException(status_code=400, detail="invalid graph id")
        self.graph_runtime._log_graph_event(safe_id, "graph_load_api")
        graphs_dir = _get_graphs_dir()
        config_path = os.path.join(graphs_dir, safe_id, "config.json")
        if not os.path.exists(config_path):
            if safe_id == "default":
                return {
                    "graph": {
                        "id": "default",
                        "name": "default",
                        "links": [],
                    }
                }
            raise HTTPException(status_code=404, detail="graph not found")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                payload = {}
            cleaned = self._sanitize_graph_payload_for_storage(payload)
            if cleaned != payload:
                try:
                    with open(config_path, "w", encoding="utf-8") as wf:
                        json.dump(cleaned, wf, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            return {"graph": cleaned}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def save_graph(self, graph_id: str, payload: dict):
        graph = (payload or {}).get("graph")
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if not safe_id:
            raise HTTPException(status_code=400, detail="invalid graph id")
        if not isinstance(graph, dict):
            raise HTTPException(status_code=400, detail="graph is required")
        save_reason = str((payload or {}).get("save_reason") or "").strip()
        source_graph_id = graph.get("source_graph_id")
        if source_graph_id is None:
            source_graph_id = (payload or {}).get("source_graph_id")
        source_graph_id = self.graph_runtime._sanitize_graph_id(source_graph_id)
        self.graph_runtime._log_graph_event(
            safe_id,
            "graph_save_api",
            source_graph_id=source_graph_id,
            save_reason=save_reason,
            nodes_count=len(graph.get("nodes") or []) if isinstance(graph.get("nodes"), list) else None,
            links_count=len(graph.get("links") or []) if isinstance(graph.get("links"), list) else None,
        )
        graphs_dir = _get_graphs_dir()
        os.makedirs(graphs_dir, exist_ok=True)
        graph_dir = os.path.join(graphs_dir, safe_id)
        os.makedirs(graph_dir, exist_ok=True)
        config_path = os.path.join(graph_dir, "config.json")
        graph = dict(graph)
        graph.pop("source_graph_id", None)
        graph = self._sanitize_graph_payload_for_storage(graph)
        graph["id"] = safe_id
        if not graph.get("name"):
            graph["name"] = safe_id
        if source_graph_id and source_graph_id != safe_id:
            source_dir = os.path.join(graphs_dir, source_graph_id)
            if os.path.isdir(source_dir):
                for entry in os.listdir(source_dir):
                    if entry == "config.json":
                        continue
                    src_path = os.path.join(source_dir, entry)
                    dst_path = os.path.join(graph_dir, entry)
                    try:
                        if os.path.isdir(src_path):
                            if os.path.exists(dst_path):
                                shutil.rmtree(dst_path)
                            shutil.copytree(src_path, dst_path)
                        elif os.path.isfile(src_path):
                            shutil.copy2(src_path, dst_path)
                    except Exception:
                        pass
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(graph, f, ensure_ascii=False, indent=2)
            updated_at = datetime.fromtimestamp(os.path.getmtime(config_path)).strftime("%Y-%m-%d %H:%M:%S")
            return {"graph": {"id": safe_id, "name": graph.get("name"), "updated_at": updated_at}}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

__all__ = ["GraphApiDomain"]
