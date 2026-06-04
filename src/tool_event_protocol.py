from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Callable

from .tool_call_protocol import ToolCallEnvelope


ToolEventCallback = Callable[[dict[str, Any]], None]


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
    diagnostics: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.event_type,
            "name": self.name,
            "call_id": self.call_id,
            "provider": self.provider,
        }
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
    return ToolLifecycleEvent(
        event_type="tool_call_end",
        name=call.name,
        call_id=call.call_id,
        provider=call.provider,
        status=status,
        duration_ms=duration_ms,
        error=error,
        result_preview=preview_tool_result(result),
        diagnostics=tuple(diagnostics or ()),
    ).to_payload()


def preview_tool_result(result: Any, limit: int = 500) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False)
        except Exception:
            text = str(result)
    text = text.replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def emit_tool_event(callback: ToolEventCallback | None, payload: dict[str, Any]) -> None:
    if not callable(callback):
        return
    callback(dict(payload))
