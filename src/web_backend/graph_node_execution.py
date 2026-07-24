import json
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from src.runtime_cancellation import CancellationRequested

from .service_host import HostBoundService
from .route_parser import NodeRouteParser
from .node_runtime_event_sink import NODE_RUNTIME_EVENTS_FILENAME
from .node_runtime_event_sink import NodeRuntimeEventSink
from .node_execution_context import bind_node_storage_context
from .node_memory_store import NodeMemoryPersistenceError
from .node_run_terminal import build_node_run_terminal_event
from .node_request_tracking import record_node_request_completion_or_log
from .node_state_machine import parse_node_state
from .shared import (
    _preview_text,
    _complete_node_config_work_with_held_output,
    _finish_node_stop_requested,
    _is_node_stop_requested,
    _set_node_config_inflight,
    _set_node_config_last_message,
    _set_node_config_runtime_event,
    _touch_node_config_last_run_at,
    _transition_node_config_to_idle,
    _read_json_dict,
    _write_json_dict,
    build_text_envelope,
    envelope_preview,
    envelope_text,
    normalize_envelope,
    _run_node_logic_with_routes,
)


class NodeStopRequested(CancellationRequested):
    pass


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

        if os.path.exists(config_path):
            cfg = _read_json_dict(config_path)

        type_id = str(cfg.get("type_id") or "").strip()
        if not type_id:
            _set_node_config_inflight(config_path, None)
            _transition_node_config_to_idle(config_path)
            return

        context: dict = {
            "task_id": trace_id,
            "graph_id": safe_graph_id,
            "node_instance_id": entry,
            "node_type_id": type_id,
            "input_index": to_input_index,
            "input_port_index": to_input_index,
            "from_output_index": from_output_index,
            "from_output_port_index": from_output_index,
            "source": source,
        }
        self._inject_node_config_into_context(context, cfg)
        bind_node_storage_context(context, config_path)
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
            update_live_output=self.core.node_live_outputs.update,
            update_live_thinking=getattr(self.core.node_live_outputs, "update_thinking", None),
            update_live_activity=getattr(self.core.node_live_outputs, "update_activity", None),
            remove_live_activity=getattr(self.core.node_live_outputs, "remove_activity", None),
            publish_live_event=self.core.node_live_outputs.publish_event,
            publish_completion_event=self.core.node_live_outputs.publish_completion_event,
            append_runtime_log=self._append_runtime_log,
            emit_runtime_event=getattr(getattr(self.core, "runtime_events", None), "emit", None),
        )
        cancel_event = self.core.node_cancellations.begin(config_path)
        if _is_node_stop_requested(config_path):
            cancel_event.set()

        def stop_requested() -> bool:
            return bool(cancel_event.is_set() or _is_node_stop_requested(config_path))

        context["begin_tool_call_cancellation"] = lambda call_id: self.core.tool_call_cancellations.begin(
            config_path,
            call_id,
        )
        context["end_tool_call_cancellation"] = lambda call_id, event: self.core.tool_call_cancellations.end(
            config_path,
            call_id,
            event,
        )

        def handle_runtime_event(payload: dict) -> None:
            if stop_requested():
                raise NodeStopRequested()
            runtime_event_sink.handle(payload)
            if stop_requested():
                raise NodeStopRequested()

        started = time.monotonic()
        started_epoch_ms = int(time.time() * 1000)

        def finish_stop_requested() -> bool:
            if not _finish_node_stop_requested(config_path):
                return False
            self._log_graph_event(
                safe_graph_id,
                "node_stop_completed",
                trace_id=trace_id,
                node_instance_id=entry,
                node_type_id=type_id,
                depth=depth,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return True

        work_completed = False
        try:
            if stop_requested():
                raise NodeStopRequested()
            runtime_event_sink.handle(
                {
                    "type": "runtime_notice",
                    "source": "node_runtime",
                    "stage": "node_run_start",
                    "message": json.dumps(
                        {
                            "trace_id": trace_id,
                            "status": "running",
                            "input_chars": len(pending_full),
                            "started_at_epoch_ms": started_epoch_ms,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
            context["stream_callback"] = handle_runtime_event
            context["cancel_event"] = cancel_event
            context["cancel_check"] = stop_requested
            self._emit_runtime_event(
                event="OnInput",
                graph_id=safe_graph_id,
                node_id=entry,
                node_type_id=type_id,
                trace_id=trace_id,
                payload={
                    "pending_preview": _preview_text(envelope_preview(pending_message), 2000),
                    "config_path": config_path,
                    "working_path": str(cfg.get("working_path") or ""),
                },
            )
            try:
                context["runtime_event_context_fragments"] = self.core.runtime_events.consume_context_fragments(
                    graph_id=safe_graph_id,
                    node_id=entry,
                )
            except Exception:
                context["runtime_event_context_fragments"] = []
            if stop_requested():
                raise NodeStopRequested()
            routed = _run_node_logic_with_routes(nodes_dir, type_id, pending_message, context)
            work_completed = True
            if finish_stop_requested():
                return
            output_message = normalize_envelope((routed or {}).get("message"), default_role="assistant")
            output_message["trace_id"] = trace_id
            routed_items = (routed or {}).get("routes") if isinstance(routed, dict) else []
            if not isinstance(routed_items, list):
                routed_items = []
            memory_sidecars = (routed or {}).get("memory_sidecars") if isinstance(routed, dict) else []
            if not isinstance(memory_sidecars, list):
                memory_sidecars = []
        except CancellationRequested:
            try:
                runtime_event_sink.handle(
                    build_node_run_terminal_event(
                        trace_id=trace_id,
                        status="cancelled",
                        provider_id=str(cfg.get("provider_id") or ""),
                        started_epoch_ms=started_epoch_ms,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error="Node run cancelled.",
                    )
                )
                finish_stop_requested()
            finally:
                self.core.node_live_outputs.clear(safe_graph_id, entry)
            return
        except Exception as e:
            if finish_stop_requested():
                self.core.node_live_outputs.clear(safe_graph_id, entry)
                return
            error_text = f"{type(e).__name__}: {str(e)}"
            error_message = f"Error: {error_text}"
            traceback_text = traceback.format_exc()
            runtime_event_sink.handle(
                build_node_run_terminal_event(
                    trace_id=trace_id,
                    status="failed",
                    provider_id=str(cfg.get("provider_id") or ""),
                    started_epoch_ms=started_epoch_ms,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error=error_text,
                )
            )
            record_node_request_completion_or_log(
                config_path,
                request_id=trace_id,
                depth=depth,
                role="system",
                message=error_message,
                state="idle",
                log_error=self._log_graph_event,
                graph_id=safe_graph_id,
                node_id=entry,
                node_type_id=type_id,
            )
            _set_node_config_inflight(config_path, None)
            _transition_node_config_to_idle(config_path)
            _set_node_config_last_message(config_path, error_message)
            _touch_node_config_last_run_at(config_path)
            try:
                self._append_node_memory_entry(
                    safe_graph_id,
                    entry,
                    "system",
                    {**build_text_envelope(error_message, role="system"), "trace_id": trace_id},
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
                traceback=_preview_text(traceback_text, 4000),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            if safe_graph_id.lower() != "companion" and self._runtime_events_available():
                self._emit_runtime_event(
                    event="WorkFailed",
                    graph_id=safe_graph_id,
                    node_id=entry,
                    node_type_id=type_id,
                    trace_id=trace_id,
                    payload={
                        "error": error_text,
                        "config_path": config_path,
                        "runtime_events_path": os.path.join(self._node_dir(safe_graph_id, entry), NODE_RUNTIME_EVENTS_FILENAME),
                    },
                )
            self.core.node_live_outputs.clear(safe_graph_id, entry)
            return
        finally:
            runtime_event_sink.close()
            self.core.node_cancellations.end(config_path, cancel_event)

        if finish_stop_requested():
            self.core.node_live_outputs.clear(safe_graph_id, entry)
            return
        output_full = envelope_text(output_message).strip()
        final_message = output_full or pending_full or envelope_preview(output_message) or envelope_preview(pending_message)
        record_node_request_completion_or_log(
            config_path,
            request_id=trace_id,
            depth=depth,
            role="assistant",
            message=final_message,
            state="idle",
            log_error=self._log_graph_event,
            graph_id=safe_graph_id,
            node_id=entry,
            node_type_id=type_id,
        )
        _set_node_config_inflight(config_path, None)
        _set_node_config_runtime_event(config_path, None)
        _set_node_config_last_message(config_path, final_message)
        try:
            self._append_node_memory_entry(safe_graph_id, entry, "assistant", output_message)
            for sidecar in memory_sidecars:
                metadata_message = normalize_envelope(sidecar, default_role="metadata")
                metadata_message["trace_id"] = trace_id
                self._append_node_memory_entry(safe_graph_id, entry, "metadata", metadata_message)
        except NodeMemoryPersistenceError as memory_error:
            self._log_memory_persistence_error(
                safe_graph_id,
                entry,
                type_id,
                trace_id,
                depth,
                memory_error,
            )
            self.core.node_live_outputs.clear(safe_graph_id, entry)
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        output_chars = max(len(output_full), int(runtime_event_sink.stream_output_chars or 0))
        runtime_event_sink.handle(
            build_node_run_terminal_event(
                trace_id=trace_id,
                status="completed",
                provider_id=str(cfg.get("provider_id") or ""),
                started_epoch_ms=started_epoch_ms,
                duration_ms=duration_ms,
                output_chars=output_chars,
                persisted_message_chars=len(final_message),
                stream_output_chars=int(runtime_event_sink.stream_output_chars or 0),
                thinking_output_chars=int(runtime_event_sink.stream_thinking_chars or 0),
            )
        )
        _touch_node_config_last_run_at(config_path)
        if safe_graph_id.lower() != "companion" and self._runtime_events_available():
            source_node_dir = self._node_dir(safe_graph_id, entry)
            self._emit_runtime_event(
                event="WorkPersisted",
                graph_id=safe_graph_id,
                node_id=entry,
                node_type_id=type_id,
                trace_id=trace_id,
                payload={
                    "final_message_preview": _preview_text(final_message, 2000),
                    "node_dir": source_node_dir,
                    "messages_path": self._node_messages_path(entry, safe_graph_id),
                    "runtime_events_path": os.path.join(source_node_dir, NODE_RUNTIME_EVENTS_FILENAME),
                    "user_context_path": os.path.join(source_node_dir, "User.md"),
                    "soul_context_path": os.path.join(source_node_dir, "Soul.md"),
                    "long_term_memory_path": os.path.join(source_node_dir, "long_term_memory.sqlite3"),
                },
            )
        self._log_graph_event(
            safe_graph_id,
            "work_persisted_alert",
            alert_id=f"work-persisted:{safe_graph_id}:{entry}:{trace_id}",
            trace_id=trace_id,
            node_instance_id=entry,
            node_type_id=type_id,
            node_name=str(cfg.get("name") or entry).strip() or entry,
            title="Node work persisted",
            message=_preview_text(final_message, 1000),
            duration_ms=duration_ms,
        )
        self._schedule_temporary_receiver_cleanup(
            graph_id=safe_graph_id,
            node_id=entry,
            cfg=_read_json_dict(config_path) if os.path.exists(config_path) else cfg,
        )
        self.core.node_live_outputs.publish_completion_event(
            safe_graph_id,
            entry,
            "node_output",
            {"type": "node_output", "duration_ms": duration_ms, "text": final_message},
            trace_id=trace_id,
        )
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
        paused_before_goal = parse_node_state(_read_json_dict(config_path).get("state")) == "stop"
        goal_result = (
            {"active": False, "should_continue": False, "paused": True}
            if paused_before_goal
            else self._evaluate_node_goal_after_persist(
                graph_id=safe_graph_id,
                node_id=entry,
                node_type_id=type_id,
                config_path=config_path,
                config=cfg,
                input_message=pending_message,
                output_message=output_message,
                trace_id=trace_id,
                depth=depth,
                wake_event=wake_event,
            )
        )
        if isinstance(goal_result, dict) and goal_result.get("should_continue"):
            _complete_node_config_work_with_held_output(config_path, {})
            self._log_graph_event(
                safe_graph_id,
                "propagate_skipped",
                trace_id=trace_id,
                node_instance_id=entry,
                node_type_id=type_id,
                depth=depth,
                reason="goal_continuation",
            )
            return

        if skip_propagation:
            _complete_node_config_work_with_held_output(config_path, {})
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
            _complete_node_config_work_with_held_output(config_path, {})
            return

        final_state, held_count = _complete_node_config_work_with_held_output(
            config_path,
            {
                "trace_id": trace_id,
                "from_node": entry,
                "next_visited": next_visited,
                "tasks": propagation_tasks,
            },
        )
        if final_state == "stop":
            self._set_node_config_last_message(config_path, f"Paused. {held_count} completed output(s) waiting to send.")
            self._log_graph_event(
                safe_graph_id,
                "propagation_paused",
                trace_id=trace_id,
                node_instance_id=entry,
                node_type_id=type_id,
                depth=depth,
                held_output_count=held_count,
                held_task_count=len(propagation_tasks),
            )
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

    def _emit_runtime_event(
        self,
        *,
        event: str,
        graph_id: str,
        node_id: str,
        node_type_id: str,
        trace_id: str,
        payload: dict,
    ) -> None:
        runtime_events = getattr(self.core, "runtime_events", None)
        emit = getattr(runtime_events, "emit", None)
        if not callable(emit):
            return
        try:
            emit(
                event=event,
                graph_id=graph_id,
                node_id=node_id,
                node_type_id=node_type_id,
                trace_id=trace_id,
                payload=payload,
            )
        except Exception as exc:
            self._log_graph_event(
                graph_id,
                "runtime_event_emit_failed",
                trace_id=trace_id,
                node_instance_id=node_id,
                node_type_id=node_type_id,
                runtime_event=event,
                error=str(exc),
            )

    def _runtime_events_available(self) -> bool:
        runtime_events = getattr(self.core, "runtime_events", None)
        return callable(getattr(runtime_events, "emit", None))

    def _schedule_temporary_receiver_cleanup(self, *, graph_id: str, node_id: str, cfg: dict) -> None:
        runtime_events = getattr(self.core, "runtime_events", None)
        cleanup = getattr(runtime_events, "cleanup", None)
        schedule = getattr(cleanup, "schedule_if_temporary", None)
        if not callable(schedule):
            return
        try:
            schedule(graph_id=graph_id, node_id=node_id, config=cfg)
        except Exception as exc:
            self._log_graph_event(
                graph_id,
                "runtime_event_temporary_cleanup_schedule_failed",
                node_instance_id=node_id,
                error=str(exc),
            )

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
