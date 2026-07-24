from __future__ import annotations

from typing import Any, Callable
import json

from src.providers.sse_debug import ProviderSseDebugMixin
from src.tool.tool_event_protocol import RuntimeNoticeEvent


PROVIDER_REQUEST_SUMMARY_STAGE = "provider_request_summary"
PROVIDER_REQUEST_COMPLETED_STAGE = "provider_request_completed"


def emit_provider_runtime_notice(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    provider: str,
    message: str,
    stage: str,
    source: str = "provider_runtime",
) -> None:
    if not callable(callback):
        return
    event = RuntimeNoticeEvent(
        message=message,
        source=source,
        stage=stage,
        provider=str(provider or "").strip() or None,
    ).to_payload()
    callback(event)


class ProviderRuntimeEventMixin(ProviderSseDebugMixin):
    def _emit_provider_runtime_notice(self, *, message: str, stage: str) -> None:
        emit_provider_runtime_notice(
            getattr(self, "tool_event_callback", None),
            provider=getattr(self, "provider_name", "provider"),
            message=message,
            stage=stage,
        )

    def _emit_retry_notice(
        self,
        *,
        error: str,
        delay: float,
        stage: str,
        attempt: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        progress = (
            f" Attempt {attempt}/{max_retries}."
            if attempt is not None and max_retries is not None
            else ""
        )
        self._emit_provider_runtime_notice(
            message=f"Request failed ({error}). Retrying in {delay:.3f}s.{progress}",
            stage=stage,
        )

    def _parse_sse_json_event(self, data_text: str, *, stage: str):
        try:
            return json.loads(data_text)
        except json.JSONDecodeError as exc:
            self._emit_provider_runtime_notice(
                message=f"Skipped malformed SSE event JSON: {exc}",
                stage=stage,
            )
            return None
