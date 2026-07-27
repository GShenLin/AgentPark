from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .contracts import CodexProtocolError


def collect_responses_stream(chunks: Iterable[bytes]) -> dict[str, Any]:
    created_response: dict[str, Any] = {}
    completed_response: dict[str, Any] = {}
    output_items: list[dict[str, Any]] = []
    text_deltas: list[str] = []
    for chunk in chunks:
        event = _event(chunk)
        if event is None:
            continue
        event_type = str(event.get("type") or "")
        if event_type == "response.created":
            response = event.get("response")
            if isinstance(response, dict):
                created_response = dict(response)
        elif event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                text_deltas.append(delta)
        elif event_type == "response.output_item.done":
            item = event.get("item")
            if isinstance(item, dict):
                output_items.append(dict(item))
        elif event_type == "response.completed":
            response = event.get("response")
            if not isinstance(response, dict):
                raise CodexProtocolError("Responses completed event requires a response object.")
            completed_response = dict(response)
        elif event_type == "response.failed":
            response = event.get("response")
            error = response.get("error") if isinstance(response, dict) else None
            message = (
                str(error.get("message") or error)
                if isinstance(error, dict)
                else str(error or "Provider failed.")
            )
            raise CodexProtocolError(message)

    if not completed_response:
        raise CodexProtocolError("Responses stream ended without response.completed.")
    result = {**created_response, **completed_response}
    result.setdefault("object", "response")
    result.setdefault("status", "completed")
    if not isinstance(result.get("output"), list):
        result["output"] = output_items
    if not isinstance(result.get("output_text"), str):
        result["output_text"] = "".join(text_deltas) or _output_text(result["output"])
    return result


def _event(chunk: bytes) -> dict[str, Any] | None:
    data_lines = [
        line.strip()[5:].lstrip()
        for line in bytes(chunk).splitlines()
        if line.strip().startswith(b"data:")
    ]
    if not data_lines:
        return None
    raw = b"\n".join(data_lines)
    if raw == b"[DONE]":
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexProtocolError("Responses stream frame is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError("Responses stream event must be an object.")
    return value


def _output_text(output: list[Any]) -> str:
    return "".join(
        str(part.get("text") or "")
        for item in output
        if isinstance(item, dict) and str(item.get("type") or "") == "message"
        for part in item.get("content", [])
        if isinstance(part, dict) and str(part.get("type") or "") in {"output_text", "text"}
    )


__all__ = ["collect_responses_stream"]
