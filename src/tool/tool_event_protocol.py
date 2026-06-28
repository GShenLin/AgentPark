from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import time
from typing import Any, Callable

from .tool_call_protocol import ToolCallEnvelope


ToolEventCallback = Callable[[dict[str, Any]], Any]


def runtime_event_timestamps() -> dict[str, Any]:
    return {
        "event_time": datetime.now().astimezone().isoformat(timespec="microseconds"),
        "monotonic_ns": time.monotonic_ns(),
    }


@dataclass(frozen=True)
class ToolResultPreview:
    text: str
    total_chars: int
    truncated: bool


@dataclass(frozen=True)
class ToolLifecycleEvent:
    event_type: str
    name: str
    call_id: str
    provider: str | None
    arguments: dict[str, Any] | None = None
    status: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    result_preview: str | None = None
    result_chars: int | None = None
    result_preview_truncated: bool | None = None
    result_tail_preview: str | None = None
    result_tail_preview_truncated: bool | None = None
    diagnostics: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.event_type,
            "name": self.name,
            "call_id": self.call_id,
            "provider": self.provider,
        }
        payload.update(runtime_event_timestamps())
        if self.arguments is not None:
            payload["arguments"] = self.arguments
        if self.status is not None:
            payload["status"] = self.status
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        if self.error:
            payload["error"] = self.error
        if self.result_preview:
            payload["result_preview"] = self.result_preview
        if self.result_chars is not None:
            payload["result_chars"] = self.result_chars
        if self.result_preview_truncated is not None:
            payload["result_preview_truncated"] = self.result_preview_truncated
        if self.result_tail_preview:
            payload["result_tail_preview"] = self.result_tail_preview
        if self.result_tail_preview_truncated is not None:
            payload["result_tail_preview_truncated"] = self.result_tail_preview_truncated
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


@dataclass(frozen=True)
class RuntimeNoticeEvent:
    message: str
    source: str
    stage: str | None = None
    name: str | None = None
    call_id: str | None = None
    provider: str | None = None

    def to_payload(self) -> dict[str, Any]:
        message = str(self.message or "").strip()
        if not message:
            raise ValueError("runtime notice requires message")
        payload: dict[str, Any] = {
            "type": "runtime_notice",
            "message": message,
            "source": str(self.source or "runtime").strip() or "runtime",
        }
        payload.update(runtime_event_timestamps())
        if self.stage:
            payload["stage"] = self.stage
        if self.name:
            payload["name"] = self.name
        if self.call_id:
            payload["call_id"] = self.call_id
        if self.provider:
            payload["provider"] = self.provider
        return payload


def now_monotonic() -> float:
    return time.monotonic()


def elapsed_ms(started_at: float) -> int:
    return max(0, int((time.monotonic() - started_at) * 1000))


def build_tool_call_start(call: ToolCallEnvelope) -> dict[str, Any]:
    return ToolLifecycleEvent(
        event_type="tool_call_start",
        name=call.name,
        call_id=call.call_id,
        provider=call.provider,
        arguments=dict(call.arguments),
    ).to_payload()


def build_tool_call_end(
    call: ToolCallEnvelope,
    *,
    status: str,
    duration_ms: int,
    error: str | None = None,
    result: Any = None,
    diagnostics: tuple[str, ...] = (),
) -> dict[str, Any]:
    result_preview = build_tool_result_preview(result)
    result_tail_preview = build_tool_result_tail_preview(result)
    return ToolLifecycleEvent(
        event_type="tool_call_end",
        name=call.name,
        call_id=call.call_id,
        provider=call.provider,
        status=status,
        duration_ms=duration_ms,
        error=error,
        result_preview=result_preview.text,
        result_chars=result_preview.total_chars,
        result_preview_truncated=result_preview.truncated,
        result_tail_preview=result_tail_preview.text,
        result_tail_preview_truncated=result_tail_preview.truncated,
        diagnostics=tuple(diagnostics or ()),
    ).to_payload()


def build_tool_result_preview(result: Any, limit: int = 500) -> ToolResultPreview:
    text = _tool_result_text(result)
    total_chars = len(text)
    if total_chars <= limit:
        return ToolResultPreview(text=text, total_chars=total_chars, truncated=False)
    return ToolResultPreview(text=text[:limit].rstrip(), total_chars=total_chars, truncated=True)


def build_tool_result_tail_preview(result: Any, limit: int = 1200) -> ToolResultPreview:
    text = _tool_result_text(result)
    total_chars = len(text)
    if total_chars <= limit:
        return ToolResultPreview(text=text, total_chars=total_chars, truncated=False)
    return ToolResultPreview(text=text[-limit:].lstrip(), total_chars=total_chars, truncated=True)


def _tool_result_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False)
        except Exception:
            text = str(result)
    return text.replace("\r\n", "\n").strip()


def preview_tool_result(result: Any, limit: int = 500) -> str:
    return build_tool_result_preview(result, limit=limit).text


def emit_tool_event(callback: ToolEventCallback | None, payload: dict[str, Any]) -> Any:
    if not callable(callback):
        return None
    return callback(dict(payload))
