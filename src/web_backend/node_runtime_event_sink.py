from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from typing import Protocol

from src.node_stream_protocol import NODE_MESSAGE_DELTA
from src.node_stream_protocol import NODE_MESSAGE_DONE
from src.node_stream_protocol import NODE_THINKING_DELTA
from src.node_stream_protocol import normalize_node_message_event
from src.media_stream_protocol import AUDIO_STREAM_EVENT_TYPES, normalize_audio_stream_event
from src.providers.provider_runtime_events import PROVIDER_REQUEST_SUMMARY_STAGE
from src.providers.provider_runtime_events import PROVIDER_REQUEST_COMPLETED_STAGE

from .runtime_event_store import normalize_runtime_event
from .runtime_event_artifacts import compact_runtime_event_record
from .node_board_view import build_board_provider_summary
from .delayed_live_activity import DelayedLiveActivityGate
from .state_store import _preview_text
from .state_store import _append_jsonl_line
from .state_store import _set_node_config_last_message
from .state_store import _set_node_config_runtime_event


LogGraphEvent = Callable[..., None]
AppendRuntimeLog = Callable[..., None]
AppendToolCallEntry = Callable[[str, str, dict], None]
RuntimeEventEmit = Callable[..., dict]
NODE_RUNTIME_EVENTS_FILENAME = "runtime_events.jsonl"


class UpdateLiveOutput(Protocol):
    def __call__(
        self,
        graph_id: str,
        node_id: str,
        text: str,
        *,
        trace_id: str = "",
        delta: str = "",
    ) -> None:
        ...


class UpdateLiveThinking(Protocol):
    def __call__(self, graph_id: str, node_id: str, text: str, *, trace_id: str = "", event: dict | None = None, delta: str = "") -> None:
        ...


class UpdateLiveActivity(Protocol):
    def __call__(
        self,
        graph_id: str,
        node_id: str,
        block: dict,
        *,
        trace_id: str = "",
        event: dict | None = None,
    ) -> None:
        ...


class RemoveLiveActivity(Protocol):
    def __call__(
        self,
        graph_id: str,
        node_id: str,
        block_id: str,
        *,
        trace_id: str = "",
        event: dict | None = None,
    ) -> None:
        ...


class PublishLiveEvent(Protocol):
    def __call__(
        self,
        graph_id: str,
        node_id: str,
        event_type: str,
        event: dict | None = None,
        *,
        trace_id: str = "",
    ) -> None:
        ...


class PublishCompletionEvent(PublishLiveEvent, Protocol):
    pass


@dataclass
class NodeRuntimeEventSink:
    graph_id: str
    node_id: str
    node_type_id: str
    config_path: str
    trace_id: str
    depth: int
    stream_last_text: str
    log_graph_event: LogGraphEvent
    append_tool_call_entry: AppendToolCallEntry
    update_live_output: UpdateLiveOutput | None = None
    update_live_thinking: UpdateLiveThinking | None = None
    update_live_activity: UpdateLiveActivity | None = None
    remove_live_activity: RemoveLiveActivity | None = None
    publish_live_event: PublishLiveEvent | None = None
    publish_completion_event: PublishCompletionEvent | None = None
    append_runtime_log: AppendRuntimeLog | None = None
    emit_runtime_event: RuntimeEventEmit | None = None
    active_tool_calls: dict[str, dict] | None = None
    completed_server_tool_calls: set[str] | None = None
    tool_live_activity_gate: DelayedLiveActivityGate | None = None
    stream_output_chars: int = 0
    stream_thinking_chars: int = 0
    stream_thinking_text: str = ""

    def __post_init__(self) -> None:
        if self.tool_live_activity_gate is None:
            self.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=1.0)

    def close(self) -> None:
        if self.tool_live_activity_gate is not None:
            self.tool_live_activity_gate.close()

    def handle(self, event: object):
        if not isinstance(event, dict):
            raise ValueError("node runtime event must be an object")

        event_type = str(event.get("type") or "").strip().lower()
        if event_type == NODE_MESSAGE_DELTA:
            normalized = normalize_node_message_event(event)
            custom_event = event.get("event")
            return self._handle_delta(normalized, custom_event=custom_event if isinstance(custom_event, dict) else None)
        if event_type == NODE_THINKING_DELTA:
            return self._handle_thinking_delta(event)
        if event_type == NODE_MESSAGE_DONE:
            return self._handle_done(normalize_node_message_event(event))
        if event_type == "runtime_notice":
            return self._handle_runtime_notice(normalize_runtime_event(event))
        if event_type in {"tool_call_start", "tool_call_end"}:
            normalized = normalize_runtime_event(event)
            return self._handle_tool_call_event(normalized, str(normalized.get("type") or event_type))
        if event_type == "server_tool_activity":
            return self._handle_server_tool_activity(normalize_runtime_event(event))
        if event_type == "response_refusal":
            return self._handle_response_refusal(event)
        if event_type in AUDIO_STREAM_EVENT_TYPES:
            normalized = normalize_audio_stream_event(event)
            if callable(self.publish_live_event):
                self.publish_live_event(
                    self.graph_id,
                    self.node_id,
                    event_type,
                    normalized,
                    trace_id=self.trace_id,
                )
            return None
        raise ValueError(f"unsupported node runtime event type: {event_type or '<empty>'}")

    def _handle_delta(self, event: dict, *, custom_event: dict | None = None) -> None:
        text = str(event.get("text") or "")
        previous_text = self.stream_last_text
        self.stream_output_chars = _advance_stream_chars(
            current_total=self.stream_output_chars,
            previous_text=previous_text,
            next_text=text,
            delta=event.get("delta"),
        )
        if text == self.stream_last_text:
            changed = False
        else:
            changed = True
            self.stream_last_text = text
            if callable(self.update_live_output):
                self.update_live_output(
                    self.graph_id,
                    self.node_id,
                    text,
                    trace_id=self.trace_id,
                    delta=str(event.get("delta") or ""),
                )
        if custom_event:
            live_event_type = str(custom_event.get("type") or "").strip().lower()
            if live_event_type and callable(self.publish_live_event):
                self.publish_live_event(self.graph_id, self.node_id, live_event_type, custom_event, trace_id=self.trace_id)
        if not changed and not custom_event:
            return

    def _handle_thinking_delta(self, event: dict) -> None:
        text = str(event.get("text") or "")
        self.stream_thinking_chars = _advance_stream_chars(
            current_total=self.stream_thinking_chars,
            previous_text=self.stream_thinking_text,
            next_text=text,
            delta=event.get("delta"),
        )
        self.stream_thinking_text = text
        if callable(self.update_live_thinking):
            self.update_live_thinking(
                self.graph_id,
                self.node_id,
                text,
                trace_id=self.trace_id,
                event=event,
                delta=str(event.get("delta") or ""),
            )

    def _handle_done(self, event: dict) -> None:
        self.close()
        text = str(event.get("text") or "")
        if text:
            _set_node_config_last_message(self.config_path, text)
            self.stream_last_text = text
        compact_event = {
            "type": "node_message_done",
            "trace_id": str(event.get("trace_id") or self.trace_id or ""),
            "text_preview": _preview_text(text, 4000),
            "text_chars": len(text),
            "metadata_keys": sorted(str(key) for key in (event.get("metadata") or {}).keys())
            if isinstance(event.get("metadata"), dict)
            else [],
        }
        self._append_node_runtime_event_record("node_message_done", compact_event)
        completion_event = {
            "type": "node_message_done",
            "text": text,
            "trace_id": str(event.get("trace_id") or self.trace_id or ""),
        }
        if callable(self.publish_completion_event):
            self.publish_completion_event(
                self.graph_id,
                self.node_id,
                "node_message_done",
                completion_event,
                trace_id=self.trace_id,
            )
        elif callable(self.publish_live_event):
            self.publish_live_event(
                self.graph_id,
                self.node_id,
                "node_message_done",
                completion_event,
                trace_id=self.trace_id,
            )
        self._append_node_runtime_log(
            "node_message_done",
            phase="done",
            message=_preview_text(text, 1000),
            output_preview=_preview_text(text, 4000),
            output_chars=len(text),
        )
        self.log_graph_event(
            self.graph_id,
            "node_message_done",
            trace_id=self.trace_id,
            node_instance_id=self.node_id,
            node_type_id=self.node_type_id,
            depth=self.depth,
            output_preview=_preview_text(text),
        )

    def _handle_runtime_notice(self, event: dict) -> None:
        _set_node_config_runtime_event(self.config_path, event)
        self._append_node_runtime_event_record("runtime_notice", event)
        message = _preview_text(str(event.get("message") or ""), 1000)
        self._append_node_runtime_log(
            "runtime_notice",
            phase=str(event.get("stage") or "").strip() or None,
            message=message,
            source=str(event.get("source") or "").strip() or None,
            stage=str(event.get("stage") or "").strip() or None,
            tool_name=str(event.get("name") or "").strip() or None,
            call_id=str(event.get("call_id") or "").strip() or None,
            provider=str(event.get("provider") or "").strip() or None,
        )
        graph_event_fields = {
            "trace_id": self.trace_id,
            "node_instance_id": self.node_id,
            "node_type_id": self.node_type_id,
            "depth": self.depth,
            "source": str(event.get("source") or "").strip() or None,
            "stage": str(event.get("stage") or "").strip() or None,
            "message": _preview_text(str(event.get("message") or ""), 1000),
            "tool_name": str(event.get("name") or "").strip() or None,
            "call_id": str(event.get("call_id") or "").strip() or None,
            "provider": str(event.get("provider") or "").strip() or None,
        }
        if str(event.get("stage") or "").strip() == PROVIDER_REQUEST_SUMMARY_STAGE:
            provider_summary = self._parse_provider_request_summary(event.get("message"))
            if provider_summary is not None:
                graph_event_fields["provider_request_summary"] = build_board_provider_summary(provider_summary)
        self.log_graph_event(self.graph_id, "runtime_notice", **graph_event_fields)
        self._emit_runtime_event("RuntimeNotice", event)
        if _looks_like_network_error(event):
            self._emit_runtime_event("NetError", event)

    def _handle_server_tool_activity(self, event: dict) -> None:
        _set_node_config_runtime_event(self.config_path, event)
        self._append_node_runtime_event_record("server_tool_activity", event)
        tool_type = str(event.get("tool_type") or "server_tool").strip() or "server_tool"
        status = str(event.get("status") or "in_progress").strip() or "in_progress"
        call_id = str(event.get("call_id") or "").strip()
        terminal_status = status in {"completed", "failed", "error", "cancelled", "timeout"}
        live_block_id = f"server_tool:{call_id}"
        gate_activity_id = live_block_id
        if (
            call_id
            and self.tool_live_activity_gate is not None
            and callable(self.update_live_activity)
        ):
            if terminal_status:
                terminal_update = None
                if tool_type != "web_search":
                    terminal_block = _server_tool_live_block(event, tool_type=tool_type, status=status)
                    terminal_update = lambda: self.update_live_activity(
                        self.graph_id,
                        self.node_id,
                        terminal_block,
                        trace_id=self.trace_id,
                        event=event,
                    )
                self.tool_live_activity_gate.finish(
                    gate_activity_id,
                    when_visible=terminal_update,
                )
            else:
                live_block = _server_tool_live_block(event, tool_type=tool_type, status=status)
                self.tool_live_activity_gate.start(
                    gate_activity_id,
                    show=lambda: self.update_live_activity(
                        self.graph_id,
                        self.node_id,
                        live_block,
                        trace_id=self.trace_id,
                        event=event,
                    ),
                    hide=lambda: self.remove_live_activity(
                        self.graph_id,
                        self.node_id,
                        live_block_id,
                        trace_id=self.trace_id,
                        event=event,
                    ) if callable(self.remove_live_activity) else None,
                )
        self._append_node_runtime_log(
            "server_tool_activity",
            phase=status,
            message=f"Server tool {status}: {tool_type}",
            tool_name=tool_type,
            call_id=str(event.get("call_id") or "").strip() or None,
            provider=str(event.get("provider") or "").strip() or None,
            status=status,
        )
        self.log_graph_event(
            self.graph_id,
            "server_tool_activity",
            trace_id=self.trace_id,
            node_instance_id=self.node_id,
            node_type_id=self.node_type_id,
            depth=self.depth,
            tool_name=tool_type,
            call_id=str(event.get("call_id") or "").strip() or None,
            provider=str(event.get("provider") or "").strip() or None,
            status=status,
        )
        if terminal_status:
            if self.completed_server_tool_calls is None:
                self.completed_server_tool_calls = set()
            if call_id not in self.completed_server_tool_calls:
                try:
                    self.append_tool_call_entry(
                        self.graph_id,
                        self.node_id,
                        _server_tool_history_event(event, tool_type=tool_type, status=status),
                    )
                except Exception as exc:
                    self._handle_tool_history_persistence_failure(exc)
                else:
                    self.completed_server_tool_calls.add(call_id)
                    self._publish_progress_updated(
                        event,
                        source_event="server_tool_activity",
                        tool_name=tool_type,
                    )
        if callable(self.publish_live_event):
            self.publish_live_event(
                self.graph_id,
                self.node_id,
                "server_tool_activity",
                event,
                trace_id=self.trace_id,
            )

    def _handle_response_refusal(self, event: dict) -> None:
        text = str(event.get("text") or "")
        item_id = str(event.get("item_id") or "refusal").strip() or "refusal"
        status = str(event.get("status") or "in_progress").strip().lower() or "in_progress"
        if callable(self.update_live_activity):
            self.update_live_activity(
                self.graph_id,
                self.node_id,
                {
                    "id": f"refusal:{item_id}",
                    "type": "refusal",
                    "label": "Refusal",
                    "status": status,
                    "text": text,
                    "provider": str(event.get("provider") or "").strip(),
                },
                trace_id=self.trace_id,
                event=event,
            )
        if callable(self.publish_live_event):
            self.publish_live_event(self.graph_id, self.node_id, "response_refusal", event, trace_id=self.trace_id)

    def _handle_tool_call_event(self, event: dict, event_type: str):
        _set_node_config_runtime_event(self.config_path, event)
        self._remember_tool_call_event(event, event_type)
        error_text = str(event.get("error") or "").strip()
        result_preview = str(event.get("result_preview") or "").strip()
        if event_type == "tool_call_start":
            self._append_tool_runtime_log(event, event_type)
            call_id = str(event.get("call_id") or "").strip()
            if (
                call_id
                and self.tool_live_activity_gate is not None
                and callable(self.update_live_activity)
            ):
                block_id = f"tool_call:{call_id}"
                block = {
                    "id": block_id,
                    "type": "tool_call",
                    "label": str(event.get("name") or "tool").strip() or "tool",
                    "status": "running",
                    "provider": str(event.get("provider") or "").strip(),
                    "call_id": call_id,
                    "arguments": event.get("arguments") if isinstance(event.get("arguments"), dict) else None,
                }
                self.tool_live_activity_gate.start(
                    block_id,
                    show=lambda: self.update_live_activity(
                        self.graph_id,
                        self.node_id,
                        block,
                        trace_id=self.trace_id,
                        event=event,
                    ),
                    hide=lambda: self.remove_live_activity(
                        self.graph_id,
                        self.node_id,
                        block_id,
                        trace_id=self.trace_id,
                        event=event,
                    ) if callable(self.remove_live_activity) else None,
                )
        self.log_graph_event(
            self.graph_id,
            event_type,
            trace_id=self.trace_id,
            node_instance_id=self.node_id,
            node_type_id=self.node_type_id,
            depth=self.depth,
            tool_name=str(event.get("name") or "tool").strip() or "tool",
            call_id=str(event.get("call_id") or "").strip() or None,
            provider=str(event.get("provider") or "").strip() or None,
            status=str(event.get("status") or "").strip() or None,
            duration_ms=event.get("duration_ms"),
            error=_preview_text(error_text, 1000) if error_text else None,
            result_preview=_preview_text(result_preview, 1000) if result_preview else None,
        )
        if event_type == "tool_call_end":
            merged = self._merged_tool_call_event(event)
            call_id = str(merged.get("call_id") or "").strip()
            if call_id and self.tool_live_activity_gate is not None:
                self.tool_live_activity_gate.finish(f"tool_call:{call_id}")
            self._append_tool_runtime_log(merged, event_type)
            persistence_warning = ""
            try:
                self.append_tool_call_entry(self.graph_id, self.node_id, merged)
            except Exception as exc:
                persistence_warning = self._handle_tool_history_persistence_failure(exc)
                merged = dict(merged)
                merged["memory_persistence_warning"] = persistence_warning
                _set_node_config_runtime_event(self.config_path, merged)
            else:
                self._publish_progress_updated(
                    merged,
                    source_event=event_type,
                    tool_name=str(merged.get("name") or "tool").strip() or "tool",
                )
            self._append_node_runtime_event_record(event_type, merged)
            if _is_failed_tool_event(merged):
                self._emit_runtime_event("ToolFailure", merged)
            if callable(self.publish_live_event):
                self.publish_live_event(self.graph_id, self.node_id, event_type, merged, trace_id=self.trace_id)
            if persistence_warning:
                return {"memory_persistence_warning": persistence_warning}
            return None
        self._append_node_runtime_event_record(event_type, event)
        if callable(self.publish_live_event):
            self.publish_live_event(self.graph_id, self.node_id, event_type, event, trace_id=self.trace_id)
        return None

    def _publish_progress_updated(self, event: dict, *, source_event: str, tool_name: str) -> None:
        self.log_graph_event(
            self.graph_id,
            "node_progress_updated",
            trace_id=self.trace_id,
            node_instance_id=self.node_id,
            node_type_id=self.node_type_id,
            depth=self.depth,
            source_event=str(source_event or "").strip(),
            tool_name=str(tool_name or "").strip() or None,
            call_id=str(event.get("call_id") or "").strip() or None,
            provider=str(event.get("provider") or "").strip() or None,
            status=str(event.get("status") or "").strip() or None,
        )

    def _append_node_runtime_event_record(self, event_type: str, event: dict) -> None:
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "event": str(event_type or "").strip(),
            "graph_id": self.graph_id,
            "node_instance_id": self.node_id,
            "node_type_id": self.node_type_id,
            "trace_id": self.trace_id,
            "depth": self.depth,
        }
        if isinstance(event, dict):
            payload["runtime_event"] = dict(event)
            if (
                str(event.get("type") or "").strip() == "runtime_notice"
                and str(event.get("stage") or "").strip()
                in {PROVIDER_REQUEST_SUMMARY_STAGE, PROVIDER_REQUEST_COMPLETED_STAGE}
            ):
                summary = self._parse_provider_request_summary(event.get("message"))
                if summary is not None:
                    key = (
                        "provider_request_summary"
                        if str(event.get("stage") or "").strip() == PROVIDER_REQUEST_SUMMARY_STAGE
                        else "provider_request_completion"
                    )
                    payload[key] = summary
        runtime_events_path = self._node_runtime_events_path()
        durable_payload = compact_runtime_event_record(payload, runtime_events_path)
        _append_jsonl_line(runtime_events_path, durable_payload)

    def _node_runtime_events_path(self) -> str:
        if not self.config_path:
            return ""
        node_dir = os.path.dirname(os.path.abspath(self.config_path))
        if not node_dir:
            return ""
        return os.path.join(node_dir, NODE_RUNTIME_EVENTS_FILENAME)

    @staticmethod
    def _parse_provider_request_summary(value: object) -> dict | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            payload = json.loads(value)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _append_tool_runtime_log(self, event: dict, event_type: str) -> None:
        tool_name = str(event.get("name") or "tool").strip() or "tool"
        call_id = str(event.get("call_id") or "").strip() or None
        provider = str(event.get("provider") or "").strip() or None
        if event_type == "tool_call_start":
            self._append_node_runtime_log(
                event_type,
                phase="start",
                message=f"Tool started: {tool_name}",
                tool_name=tool_name,
                call_id=call_id,
                provider=provider,
                arguments=event.get("arguments") if isinstance(event.get("arguments"), dict) else None,
                event_time=event.get("event_time"),
                monotonic_ns=event.get("monotonic_ns"),
            )
            return

        error_text = str(event.get("error") or "").strip()
        result_preview = str(event.get("result_preview") or "").strip()
        status = str(event.get("status") or "completed").strip() or "completed"
        self._append_node_runtime_log(
            event_type,
            level="error" if error_text else "info",
            phase="end",
            message=f"Tool finished: {tool_name}",
            tool_name=tool_name,
            call_id=call_id,
            provider=provider,
            status=status,
            duration_ms=event.get("duration_ms"),
            error=_preview_text(error_text, 4000) if error_text else None,
            result_preview=_preview_text(result_preview, 4000) if result_preview else None,
            result_chars=event.get("result_chars"),
            result_preview_truncated=event.get("result_preview_truncated"),
            result_tail_preview=(
                _preview_text(str(event.get("result_tail_preview") or ""), 4000)
                if str(event.get("result_tail_preview") or "").strip()
                else None
            ),
            result_tail_preview_truncated=event.get("result_tail_preview_truncated"),
            diagnostics=event.get("diagnostics") if isinstance(event.get("diagnostics"), list) else None,
            arguments=event.get("arguments") if isinstance(event.get("arguments"), dict) else None,
            event_time=event.get("event_time"),
            monotonic_ns=event.get("monotonic_ns"),
        )

    def _append_node_runtime_log(
        self,
        event_type: str,
        *,
        level: str = "info",
        phase: str | None = None,
        message: str = "",
        **fields,
    ) -> None:
        if not callable(self.append_runtime_log):
            return
        payload = {
            "trace_id": self.trace_id,
            "node_instance_id": self.node_id,
            "node_type_id": self.node_type_id,
            "depth": self.depth,
            "level": level,
            "phase": phase,
            "message": message,
        }
        for key, value in fields.items():
            if value is not None:
                payload[key] = value
        try:
            self.append_runtime_log(self.graph_id, event_type, **payload)
        except Exception as exc:
            warning = f"{type(exc).__name__}: {exc}"
            self.log_graph_event(
                self.graph_id,
                "runtime_event_emit_failed",
                trace_id=self.trace_id,
                node_instance_id=self.node_id,
                node_type_id=self.node_type_id,
                runtime_event=event_name,
                error=_preview_text(warning, 1000),
            )

    def _remember_tool_call_event(self, event: dict, event_type: str) -> None:
        call_id = str(event.get("call_id") or "").strip()
        if not call_id or event_type != "tool_call_start":
            return
        if self.active_tool_calls is None:
            self.active_tool_calls = {}
        self.active_tool_calls[call_id] = dict(event)

    def _merged_tool_call_event(self, event: dict) -> dict:
        call_id = str(event.get("call_id") or "").strip()
        if not call_id or self.active_tool_calls is None:
            return dict(event)
        start_event = self.active_tool_calls.pop(call_id, None)
        if not isinstance(start_event, dict):
            return dict(event)
        merged = dict(start_event)
        merged.update(dict(event))
        return merged

    def _handle_tool_history_persistence_failure(self, exc: Exception) -> str:
        warning = f"{type(exc).__name__}: {exc}"
        self.log_graph_event(
            self.graph_id,
            "node_memory_persist_failed",
            trace_id=self.trace_id,
            node_instance_id=self.node_id,
            node_type_id=self.node_type_id,
            depth=self.depth,
            target="tool_history",
            error=_preview_text(warning, 1000),
            failures=_persistence_failures(exc),
        )
        if callable(self.publish_live_event):
            self.publish_live_event(
                self.graph_id,
                self.node_id,
                "runtime_notice",
                {
                    "type": "runtime_notice",
                    "source": "node_memory",
                    "stage": "tool_history_persist",
                    "message": f"Tool history persistence failed: {_preview_text(warning, 500)}",
                },
                trace_id=self.trace_id,
            )
        return warning

    def _emit_runtime_event(self, event_name: str, payload: dict) -> None:
        if not callable(self.emit_runtime_event):
            return
        try:
            self.emit_runtime_event(
                event=event_name,
                graph_id=self.graph_id,
                node_id=self.node_id,
                node_type_id=self.node_type_id,
                trace_id=self.trace_id,
                payload={
                    **dict(payload),
                    "runtime_events_path": self._node_runtime_events_path(),
                },
            )
        except Exception:
            return


def _persistence_failures(exc: Exception) -> list[dict[str, str]]:
    failures = getattr(exc, "failures", None)
    if not isinstance(failures, (list, tuple)):
        return []
    output: list[dict[str, str]] = []
    for failure in failures:
        output.append(
            {
                "target": str(getattr(failure, "target", "") or ""),
                "path": str(getattr(failure, "path", "") or ""),
                "error": str(getattr(failure, "error", "") or ""),
            }
        )
    return output


def _is_failed_tool_event(event: dict) -> bool:
    status = str(event.get("status") or "").strip().lower()
    error = str(event.get("error") or "").strip()
    return bool(error) or status in {"error", "blocked", "timeout", "exception", "stopped", "failed"}


def _server_tool_history_event(event: dict, *, tool_type: str, status: str) -> dict:
    history_event = {
        "call_id": str(event.get("call_id") or "").strip(),
        "name": tool_type,
        "provider": str(event.get("provider") or "").strip(),
        "status": status,
    }
    action = event.get("action")
    if isinstance(action, dict):
        history_event["arguments"] = dict(action)
    sources = event.get("sources")
    if isinstance(sources, list) and sources:
        history_event["result_preview"] = f"{len(sources)} source{'s' if len(sources) != 1 else ''}"
        history_event["sources"] = [dict(item) for item in sources if isinstance(item, dict)]
    details = event.get("details")
    if isinstance(details, dict) and details:
        history_event["details"] = dict(details)
    if status in {"failed", "error", "cancelled", "timeout"}:
        history_event["error"] = str(event.get("error") or f"Server tool {status}").strip()
    return history_event


def _server_tool_live_block(event: dict, *, tool_type: str, status: str) -> dict:
    label_by_type = {
        "web_search": "WebSearch",
        "file_search": "FileSearch",
        "image_generation": "ImageGeneration",
    }
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    text = ""
    if tool_type == "web_search":
        text = _web_search_display_query(action, details)
    elif tool_type == "file_search":
        text = str(action.get("query") or action.get("search_query") or details.get("query") or "").strip()
    elif tool_type == "image_generation":
        text = str(action.get("prompt") or details.get("prompt") or details.get("revised_prompt") or "").strip()
    block = {
        "id": f"server_tool:{str(event.get('call_id') or '').strip()}",
        "type": tool_type,
        "label": "Web Searching" if tool_type == "web_search" else label_by_type.get(tool_type, "".join(part.title() for part in tool_type.split("_")) or "Tool"),
        "status": status,
        "provider": str(event.get("provider") or "").strip(),
        "call_id": str(event.get("call_id") or "").strip(),
    }
    if text:
        block["text"] = text
    sources = event.get("sources")
    if isinstance(sources, list) and sources:
        block["sources"] = [dict(item) for item in sources if isinstance(item, dict)]
    if action:
        block["action"] = dict(action)
    if details:
        block["details"] = dict(details)
    return block


def _web_search_display_query(action: dict, details: dict) -> str:
    for value in (
        action.get("query"),
        action.get("search_query"),
        details.get("query"),
        details.get("search_query"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    for value in (action.get("queries"), details.get("queries")):
        if not isinstance(value, list):
            continue
        for query in value:
            text = str(query or "").strip()
            if text:
                return text
    return ""


def _looks_like_network_error(event: dict) -> bool:
    text = " ".join(
        str(event.get(key) or "")
        for key in ("message", "stage", "source", "error", "status")
    ).lower()
    return any(token in text for token in ("network", "timeout", "retry", "connection", "connect", "http", "rate limit"))


def _advance_stream_chars(
    *,
    current_total: int,
    previous_text: str,
    next_text: str,
    delta: object,
) -> int:
    total = max(0, int(current_total or 0))
    delta_text = str(delta or "")
    if delta_text:
        return total + len(delta_text)
    if next_text.startswith(previous_text):
        return total + max(0, len(next_text) - len(previous_text))
    return max(total, len(next_text))
