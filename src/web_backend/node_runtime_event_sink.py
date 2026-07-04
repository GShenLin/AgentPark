from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from typing import Protocol

from src.node_stream_protocol import NODE_MESSAGE_DELTA
from src.node_stream_protocol import NODE_MESSAGE_DONE
from src.node_stream_protocol import normalize_node_message_event

from .runtime_event_store import normalize_runtime_event
from .state_store import _preview_text
from .state_store import _append_jsonl_line
from .state_store import _set_node_config_last_message
from .state_store import _set_node_config_runtime_event


LogGraphEvent = Callable[..., None]
AppendRuntimeLog = Callable[..., None]
AppendToolCallEntry = Callable[[str, str, dict], None]
NODE_RUNTIME_EVENTS_FILENAME = "runtime_events.jsonl"


class UpdateLiveOutput(Protocol):
    def __call__(self, graph_id: str, node_id: str, text: str, *, trace_id: str = "") -> None:
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
    publish_live_event: PublishLiveEvent | None = None
    publish_completion_event: PublishCompletionEvent | None = None
    append_runtime_log: AppendRuntimeLog | None = None
    active_tool_calls: dict[str, dict] | None = None

    def handle(self, event: object):
        if not isinstance(event, dict):
            raise ValueError("node runtime event must be an object")

        event_type = str(event.get("type") or "").strip().lower()
        if event_type == NODE_MESSAGE_DELTA:
            normalized = normalize_node_message_event(event)
            custom_event = event.get("event")
            return self._handle_delta(normalized, custom_event=custom_event if isinstance(custom_event, dict) else None)
        if event_type == NODE_MESSAGE_DONE:
            return self._handle_done(normalize_node_message_event(event))
        if event_type == "runtime_notice":
            return self._handle_runtime_notice(normalize_runtime_event(event))
        if event_type in {"tool_call_start", "tool_call_end"}:
            normalized = normalize_runtime_event(event)
            return self._handle_tool_call_event(normalized, str(normalized.get("type") or event_type))
        raise ValueError(f"unsupported node runtime event type: {event_type or '<empty>'}")

    def _handle_delta(self, event: dict, *, custom_event: dict | None = None) -> None:
        text = str(event.get("text") or "")
        if text == self.stream_last_text:
            changed = False
        else:
            changed = True
            self.stream_last_text = text
            if callable(self.update_live_output):
                self.update_live_output(self.graph_id, self.node_id, text, trace_id=self.trace_id)
        if custom_event:
            live_event_type = str(custom_event.get("type") or "").strip().lower()
            if live_event_type and callable(self.publish_live_event):
                self.publish_live_event(self.graph_id, self.node_id, live_event_type, custom_event, trace_id=self.trace_id)
        if not changed and not custom_event:
            return

    def _handle_done(self, event: dict) -> None:
        text = str(event.get("text") or "")
        if text:
            _set_node_config_last_message(self.config_path, text)
            self.stream_last_text = text
        self._append_node_runtime_event_record("node_message_done", event)
        if callable(self.publish_completion_event):
            self.publish_completion_event(self.graph_id, self.node_id, "node_message_done", event, trace_id=self.trace_id)
        elif callable(self.publish_live_event):
            self.publish_live_event(self.graph_id, self.node_id, "node_message_done", event, trace_id=self.trace_id)
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
        self.log_graph_event(
            self.graph_id,
            "runtime_notice",
            trace_id=self.trace_id,
            node_instance_id=self.node_id,
            node_type_id=self.node_type_id,
            depth=self.depth,
            source=str(event.get("source") or "").strip() or None,
            stage=str(event.get("stage") or "").strip() or None,
            message=_preview_text(str(event.get("message") or ""), 1000),
            tool_name=str(event.get("name") or "").strip() or None,
            call_id=str(event.get("call_id") or "").strip() or None,
            provider=str(event.get("provider") or "").strip() or None,
        )

    def _handle_tool_call_event(self, event: dict, event_type: str):
        _set_node_config_runtime_event(self.config_path, event)
        self._remember_tool_call_event(event, event_type)
        error_text = str(event.get("error") or "").strip()
        result_preview = str(event.get("result_preview") or "").strip()
        if event_type == "tool_call_start":
            self._append_tool_runtime_log(event, event_type)
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
            self._append_tool_runtime_log(merged, event_type)
            persistence_warning = ""
            try:
                self.append_tool_call_entry(self.graph_id, self.node_id, merged)
            except Exception as exc:
                persistence_warning = self._handle_tool_history_persistence_failure(exc)
                merged = dict(merged)
                merged["memory_persistence_warning"] = persistence_warning
                _set_node_config_runtime_event(self.config_path, merged)
            self._append_node_runtime_event_record(event_type, merged)
            if callable(self.publish_live_event):
                self.publish_live_event(self.graph_id, self.node_id, event_type, merged, trace_id=self.trace_id)
            if persistence_warning:
                return {"memory_persistence_warning": persistence_warning}
            return None
        self._append_node_runtime_event_record(event_type, event)
        if callable(self.publish_live_event):
            self.publish_live_event(self.graph_id, self.node_id, event_type, event, trace_id=self.trace_id)
        return None

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
                and str(event.get("stage") or "").strip() == "openai_responses_request_summary"
            ):
                summary = self._parse_provider_request_summary(event.get("message"))
                if summary is not None:
                    payload["provider_request_summary"] = summary
        _append_jsonl_line(self._node_runtime_events_path(), payload)

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
        except Exception:
            return

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
