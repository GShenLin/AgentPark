"""Strict parser for documented Seedream image-generation SSE events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


PARTIAL_SUCCEEDED = "image_generation.partial_succeeded"
PARTIAL_FAILED = "image_generation.partial_failed"
COMPLETED = "image_generation.completed"


def merge_seedream_stream_events(events: Iterable[Mapping[str, object]]) -> dict:
    indexed_items: dict[int, dict] = {}
    result: dict = {"data": []}
    completed = False
    request_error = False

    for raw_event in events:
        if not isinstance(raw_event, Mapping):
            raise ValueError("Image generation SSE event must be a JSON object")
        event = dict(raw_event)
        event_type = str(event.get("type") or "").strip()
        if completed or request_error:
            raise ValueError("Image generation SSE emitted an event after its terminal event")

        if event_type == PARTIAL_SUCCEEDED:
            image_index = _image_index(event)
            _require_new_index(indexed_items, image_index)
            url = str(event.get("url") or "").strip()
            b64_json = str(event.get("b64_json") or "").strip()
            if bool(url) == bool(b64_json):
                raise ValueError("partial_succeeded must contain exactly one of url or b64_json")
            item = {
                "image_index": image_index,
                "size": str(event.get("size") or "").strip(),
            }
            item["url" if url else "b64_json"] = url or b64_json
            indexed_items[image_index] = item
            _copy_identity(result, event)
            continue

        if event_type == PARTIAL_FAILED:
            image_index = _image_index(event)
            _require_new_index(indexed_items, image_index)
            error = event.get("error")
            if not isinstance(error, Mapping):
                raise ValueError("partial_failed must contain an error object")
            indexed_items[image_index] = {
                "image_index": image_index,
                "error": _normalize_error(error),
            }
            _copy_identity(result, event)
            continue

        if event_type == COMPLETED:
            _copy_identity(result, event)
            tools = event.get("tools")
            usage = event.get("usage")
            if tools is not None and not isinstance(tools, list):
                raise ValueError("completed.tools must be an array")
            if usage is not None and not isinstance(usage, Mapping):
                raise ValueError("completed.usage must be an object")
            result["tools"] = list(tools or [])
            result["usage"] = dict(usage or {})
            completed = True
            continue

        if not event_type and isinstance(event.get("error"), Mapping):
            result["error"] = _normalize_error(event["error"])
            request_error = True
            continue
        raise ValueError(f"Unsupported image generation SSE event type: {event_type or '<empty>'}")

    if request_error:
        return result
    if not completed:
        raise ValueError("Image generation SSE ended before image_generation.completed")
    indexes = sorted(indexed_items)
    if indexes and indexes != list(range(indexes[-1] + 1)):
        raise ValueError("Image generation SSE image_index values must be contiguous from 0")
    result["data"] = [indexed_items[index] for index in indexes]
    return result


def _image_index(event: Mapping[str, object]) -> int:
    raw_index = event.get("image_index")
    if isinstance(raw_index, bool):
        raise ValueError("image_index must be a non-negative integer")
    try:
        image_index = int(raw_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("image_index must be a non-negative integer") from exc
    if image_index < 0 or str(raw_index).strip() != str(image_index):
        raise ValueError("image_index must be a non-negative integer")
    return image_index


def _require_new_index(indexed_items: dict[int, dict], image_index: int) -> None:
    if image_index in indexed_items:
        raise ValueError(f"Duplicate image generation SSE image_index: {image_index}")


def _copy_identity(result: dict, event: Mapping[str, object]) -> None:
    for field in ("model", "created"):
        if field not in event:
            raise ValueError(f"Image generation SSE event is missing {field}")
        value = event[field]
        if field in result and result[field] != value:
            raise ValueError(f"Image generation SSE {field} changed within one request")
        result[field] = value


def _normalize_error(error: Mapping[str, object]) -> dict[str, str]:
    code = str(error.get("code") or "").strip()
    message = str(error.get("message") or "").strip()
    if not code or not message:
        raise ValueError("Image generation SSE error must contain code and message")
    return {"code": code, "message": message}
