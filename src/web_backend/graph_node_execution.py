import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from .service_host import HostBoundService
from .route_parser import NodeRouteParser
from .node_runtime_event_sink import NodeRuntimeEventSink
from .node_memory_store import NodeMemoryPersistenceError
from .shared import (
    _preview_text,
    _set_node_config_inflight,
    _set_node_config_last_message,
    _set_node_config_runtime_event,
    _touch_node_config_last_run_at,
    _transition_node_config_to_idle,
    _write_json_dict,
    build_text_envelope,
    envelope_preview,
    envelope_text,
    normalize_envelope,
    _run_node_logic_with_routes,
)


class GraphNodeExecution(HostBoundService):
    def _run_single_node_iteration(
        self,
        *,
        safe_graph_id: str,
        entry: str,
        cfg: dict,
        config_path: str,
        pending_item: dict,
        outgoing: dict[str, list[dict]],
        nodes_dir: str,
        wake_event,
    ) -> None:
        pending_message, trace_id, link_id, from_output_index, to_input_index, source, depth, visited = self._parse_pending_node_item(
            pending_item
        )
        from_node = str(pending_item.get("from") or "").strip()

        type_id = str(cfg.get("type_id") or "").strip()
        if not type_id:
            _set_node_config_inflight(config_path, None)
            _transition_node_config_to_idle(config_path)
            return

        context: dict = {
            "graph_id": safe_graph_id,
            "node_instance_id": entry,
            "node_type_id": type_id,
            "input_index": to_input_index,
            "input_port_index": to_input_index,
            "from_output_index": from_output_index,
            "from_output_port_index": from_output_index,
        }
        self._inject_node_config_into_context(context, cfg)
        self._log_graph_event(
            safe_graph_id,
            "node_dequeue",
            trace_id=trace_id,
            node_instance_id=entry,
            node_type_id=type_id,
            depth=depth,
            link_id=link_id or None,
            from_node=from_node or None,
            from_output_index=from_output_index,
            to_input_index=to_input_index,
            source=source or None,
            input_preview=_preview_text(envelope_preview(pending_message)),
        )
        pending_full = envelope_text(pending_message).strip()
        _set_node_config_runtime_event(config_path, None, reset_history=True)
        _set_node_config_last_message(config_path, pending_full or envelope_preview(pending_message))
        runtime_event_sink = NodeRuntimeEventSink(
            graph_id=safe_graph_id,
            node_id=entry,
            node_type_id=type_id,
            config_path=config_path,
            trace_id=trace_id,
            depth=depth,
            stream_last_text=str(pending_full or ""),
            log_graph_event=self._log_graph_event,
            append_tool_call_entry=self._append_node_tool_call_entry,
        )

        started = time.monotonic()
        try:
            context["stream_callback"] = runtime_event_sink.handle
            routed = _run_node_logic_with_routes(nodes_dir, type_id, pending_message, context)
            output_message = normalize_envelope((routed or {}).get("message"), default_role="assistant")
            routed_items = (routed or {}).get("routes") if isinstance(routed, dict) else []
            if not isinstance(routed_items, list):
                routed_items = []
        except Exception as e:
            _set_node_config_inflight(config_path, None)
            _transition_node_config_to_idle(config_path)
            error_text = f"{type(e).__name__}: {str(e)}"
            _set_node_config_last_message(config_path, f"Error: {error_text}")
            _touch_node_config_last_run_at(config_path)
            try:
                self._append_node_memory_entry(
                    safe_graph_id,
                    entry,
                    "system",
                    build_text_envelope(f"Error: {error_text}", role="system"),
                )
            except NodeMemoryPersistenceError as memory_error:
                self._log_memory_persistence_error(
                    safe_graph_id,
                    entry,
                    type_id,
                    trace_id,
                    depth,
                    memory_error,
                )
            self._log_graph_event(
                safe_graph_id,
                "node_error",
                trace_id=trace_id,
                node_instance_id=entry,
                node_type_id=type_id,
                depth=depth,
                link_id=link_id or None,
                error=error_text,
                traceback=_preview_text(traceback.format_exc(), 4000),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return

        _set_node_config_inflight(config_path, None)
        _transition_node_config_to_idle(config_path)
        output_full = envelope_text(output_message).strip()
        final_message = output_full or pending_full or envelope_preview(output_message) or envelope_preview(pending_message)
        _set_node_config_runtime_event(config_path, None)
        _set_node_config_last_message(config_path, final_message)
        _touch_node_config_last_run_at(config_path)
        try:
            self._append_node_memory_entry(safe_graph_id, entry, "assistant", output_message)
        except NodeMemoryPersistenceError as memory_error:
            self._log_memory_persistence_error(
                safe_graph_id,
                entry,
                type_id,
                trace_id,
                depth,
                memory_error,
            )
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        skip_propagation = self._should_skip_propagation(output_message)
        self._log_graph_event(
            safe_graph_id,
            "node_output",
            trace_id=trace_id,
            node_instance_id=entry,
            node_type_id=type_id,
            depth=depth,
            link_id=link_id or None,
            duration_ms=duration_ms,
            output_preview=_preview_text(envelope_preview(output_message)),
            skip_propagation=skip_propagation,
        )

        if skip_propagation:
            self._log_graph_event(
                safe_graph_id,
                "propagate_skipped",
                trace_id=trace_id,
                node_instance_id=entry,
                node_type_id=type_id,
                depth=depth,
                reason="tool_call_or_empty",
            )
            return

        next_visited = visited[-50:] + [entry]
        propagation_tasks: list[dict] = []
        links_by_output_index: dict[int, list[dict]] = {}
        for link in outgoing.get(entry, []):
            out_idx = NodeRouteParser.parse_port_index((link or {}).get("from_output_index"))
            if out_idx is None:
                out_idx = 0
            links_by_output_index.setdefault(out_idx, []).append(link)

        for route in routed_items:
            if not isinstance(route, dict):
                continue
            route_output_index = NodeRouteParser.parse_port_index(route.get("output_index"))
            if route_output_index is None:
                route_output_index = 0
            route_payload = normalize_envelope(route.get("payload"), default_role="assistant")
            for link in links_by_output_index.get(route_output_index, []):
                to_input_index = NodeRouteParser.parse_port_index((link or {}).get("to_input_index"))
                if to_input_index is None:
                    to_input_index = 0
                to_id = str((link or {}).get("to") or "").strip()
                if not to_id:
                    continue
                target_cfg_path = self._node_config_path(to_id, safe_graph_id)
                if not target_cfg_path or not os.path.exists(target_cfg_path):
                    self._log_graph_event(
                        safe_graph_id,
                        "propagate_missing_target",
                        trace_id=trace_id,
                        from_node=entry,
                        to_node=to_id,
                        link_id=str((link or {}).get("id") or "").strip() or None,
                        from_output_index=route_output_index,
                        to_input_index=to_input_index,
                    )
                    continue
                propagation_tasks.append(
                    {
                        "target_graph_id": safe_graph_id,
                        "target_cfg_path": target_cfg_path,
                        "to_id": to_id,
                        "from_node": entry,
                        "route_output_index": route_output_index,
                        "to_input_index": to_input_index,
                        "next_depth": depth + 1,
                        "route_payload": route_payload,
                        "link_id": str((link or {}).get("id") or "").strip(),
                    }
                )

        if type_id == "event_node":
            event_key = str(cfg.get("EventKey") or "").strip()
            if event_key:
                for route in routed_items:
                    if isinstance(route, dict):
                        propagation_tasks.extend(
                            self._collect_event_dispatch_tasks(
                                source_graph_id=safe_graph_id,
                                source_node_id=entry,
                                event_key=event_key,
                                route_payload=normalize_envelope(route.get("payload"), default_role="assistant"),
                                trace_id=trace_id,
                                next_visited=next_visited,
                            )
                        )

        if not propagation_tasks:
            return

        worker_count = min(8, len(propagation_tasks))
        if worker_count <= 1:
            for task in propagation_tasks:
                self._enqueue_graph_task(task, safe_graph_id, entry, trace_id, next_visited, wake_event)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(
                        self._enqueue_graph_task,
                        task,
                        safe_graph_id,
                        entry,
                        trace_id,
                        next_visited,
                        wake_event,
                    )
                    for task in propagation_tasks
                ]
                for future in futures:
                    try:
                        future.result()
                    except Exception as e:
                        self._log_graph_event(
                            safe_graph_id,
                            "propagate_enqueue_error",
                            trace_id=trace_id,
                            from_node=entry,
                            error=str(e),
                        )
        wake_event.set()

    def _log_memory_persistence_error(
        self,
        graph_id: str,
        node_id: str,
        node_type_id: str,
        trace_id: str,
        depth: int,
        error: NodeMemoryPersistenceError,
    ) -> None:
        self._log_graph_event(
            graph_id,
            "node_memory_persist_failed",
            trace_id=trace_id,
            node_instance_id=node_id,
            node_type_id=node_type_id,
            depth=depth,
            error=str(error),
            failures=[
                {
                    "target": failure.target,
                    "path": failure.path,
                    "error": failure.error,
                }
                for failure in error.failures
            ],
        )
