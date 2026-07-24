from __future__ import annotations

from typing import Any


RESPONSE_REFUSAL = "response_refusal"


def build_response_refusal_event(
    *,
    delta: object,
    text: object,
    item_id: object = "",
    output_index: int | None = None,
    content_index: int | None = None,
    provider: object = "",
    status: object = "in_progress",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": RESPONSE_REFUSAL,
        "delta": "" if delta is None else str(delta),
        "text": "" if text is None else str(text),
        "status": str(status or "in_progress").strip().lower() or "in_progress",
    }
    for key, value in (("item_id", item_id), ("provider", provider)):
        normalized = str(value or "").strip()
        if normalized:
            payload[key] = normalized
    if output_index is not None:
        payload["output_index"] = int(output_index)
    if content_index is not None:
        payload["content_index"] = int(content_index)
    return payload
