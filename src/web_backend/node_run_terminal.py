from __future__ import annotations

import json
import time


NODE_RUN_SUMMARY_STAGE = "node_run_summary"


def build_node_run_terminal_event(
    *,
    trace_id: str,
    status: str,
    started_epoch_ms: int,
    duration_ms: int,
    provider_id: str = "",
    output_chars: int = 0,
    persisted_message_chars: int = 0,
    stream_output_chars: int = 0,
    thinking_output_chars: int = 0,
    error: str = "",
) -> dict:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"completed", "failed", "cancelled"}:
        raise ValueError(f"unsupported node terminal status: {status!r}")
    payload = {
        "trace_id": str(trace_id or "").strip(),
        "status": normalized_status,
        "output_chars": max(0, int(output_chars or 0)),
        "persisted_message_chars": max(0, int(persisted_message_chars or 0)),
        "stream_output_chars": max(0, int(stream_output_chars or 0)),
        "thinking_output_chars": max(0, int(thinking_output_chars or 0)),
        "duration_ms": max(0, int(duration_ms or 0)),
        "total_duration_ms": max(0, int(duration_ms or 0)),
        "started_at_epoch_ms": max(0, int(started_epoch_ms or 0)),
        "completed_at_epoch_ms": int(time.time() * 1000),
    }
    if error:
        payload["error"] = str(error)
    event = {
        "type": "runtime_notice",
        "source": "node_runtime",
        "stage": NODE_RUN_SUMMARY_STAGE,
        "message": json.dumps(payload, ensure_ascii=False, sort_keys=True),
    }
    if provider_id:
        event["provider"] = str(provider_id).strip()
    return event
