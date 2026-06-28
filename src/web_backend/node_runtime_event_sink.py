from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from typing import Protocol

from src.node_stream_protocol import NODE_MESSAGE_DELTA
from src.node_stream_protocol import NODE_MESSAGE_DONE
from src.node_stream_protocol import normalize_node_message_event

from .runtime_event_store import normalize_runtime_event
from .state_store import _preview_text
from .state_store import _set_node_config_last_message
from .state_store import _set_node_config_runtime_event


LogGraphEvent = Callable[..., None]
AppendToolCallEntry = Callable[[str, str, dict], None]
ClearLiveOutput = Callable[[str, str], None]


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
    clear_live_output: ClearLiveOutput | None = None
    publish_live_event: PublishLiveEvent | None = None
    active_tool_calls: dict[str, dict] | None = None

    def handle(self, event: object):
        if not isinstance(event, dict):
            raise ValueError("node runtime event must be an object")

        event_type = str(event.get("type") or "").strip().lower()
        if event_type == NODE_MESSAGE_DELTA:
            return self._handle_delta(normalize_node_message_event(event))
        if event_type == NODE_MESSAGE_DONE:
            return self._handle_done(normalize_node_message_event(event))
        if event_type == "runtime_notice":
            return self._handle_runtime_notice(normalize_runtime_event(event))
        if event_type in {"tool_call_start", "tool_call_end"}:
            normalized = normalize_runtime_event(event)
            return self._handle_tool_call_event(normalized, str(normalized.get("type") or event_type))
        raise ValueError(f"unsupported node runtime event type: {event_type or '<empty>'}")

    def _handle_delta(self, event: dict) -> None:
        text = str(event.get("text") or "")
        if text == self.stream_last_text:
            return
        self.stream_last_text = text
        _set_node_config_last_message(self.config_path, text)
        if callable(self.update_live_output):
            self.update_live_output(self.graph_id, self.node_id, text, trace_id=self.trace_id)

    def _handle_done(self, event: dict) -> None:
        text = str(event.get("text") or "")
        if text:
            _set_node_config_last_message(self.config_path, text)
            self.stream_last_text = text
        if callable(self.clear_live_output):
            self.clear_live_output(self.graph_id, self.node_id)
        if callable(self.publish_live_event):
            self.publish_live_event(self.graph_id, self.node_id, "node_message_done", event, trace_id=self.trace_id)
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
            persistence_warning = ""
            try:
                self.append_tool_call_entry(self.graph_id, self.node_id, merged)
            except Exception as exc:
                persistence_warning = self._handle_tool_history_persistence_failure(exc)
                merged = dict(merged)
                merged["memory_persistence_warning"] = persistence_warning
                _set_node_config_runtime_event(self.config_path, merged)
            if callable(self.publish_live_event):
                self.publish_live_event(self.graph_id, self.node_id, event_type, merged, trace_id=self.trace_id)
            if persistence_warning:
                return {"memory_persistence_warning": persistence_warning}
            return None
        elif callable(self.publish_live_event):
            self.publish_live_event(self.graph_id, self.node_id, event_type, event, trace_id=self.trace_id)
        return None

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
