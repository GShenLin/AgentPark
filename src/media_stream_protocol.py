"""Runtime event contract for incremental media playback."""
from __future__ import annotations

import base64


AUDIO_STREAM_START = "audio_stream_start"
AUDIO_STREAM_CHUNK = "audio_stream_chunk"
AUDIO_STREAM_END = "audio_stream_end"
AUDIO_STREAM_EVENT_TYPES = {AUDIO_STREAM_START, AUDIO_STREAM_CHUNK, AUDIO_STREAM_END}


def build_audio_stream_start(*, stream_id: str, mime: str, audio_format: str, sample_rate: int) -> dict:
    return normalize_audio_stream_event({
        "type": AUDIO_STREAM_START,
        "stream_id": stream_id,
        "mime": mime,
        "format": audio_format,
        "sample_rate": sample_rate,
    })


def build_audio_stream_chunk(*, stream_id: str, sequence: int, data: bytes) -> dict:
    return normalize_audio_stream_event({
        "type": AUDIO_STREAM_CHUNK,
        "stream_id": stream_id,
        "sequence": sequence,
        "data": base64.b64encode(data).decode("ascii"),
    })


def build_audio_stream_end(*, stream_id: str, sequence: int) -> dict:
    return normalize_audio_stream_event({
        "type": AUDIO_STREAM_END,
        "stream_id": stream_id,
        "sequence": sequence,
    })


def normalize_audio_stream_event(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("audio stream event must be an object")
    event_type = str(value.get("type") or "").strip().lower()
    if event_type not in AUDIO_STREAM_EVENT_TYPES:
        raise ValueError(f"unsupported audio stream event type: {event_type or '<empty>'}")
    stream_id = str(value.get("stream_id") or "").strip()
    if not stream_id:
        raise ValueError("audio stream event requires stream_id")
    output = {"type": event_type, "stream_id": stream_id}
    if event_type == AUDIO_STREAM_START:
        mime = str(value.get("mime") or "").strip().lower()
        audio_format = str(value.get("format") or "").strip().lower()
        sample_rate = int(value.get("sample_rate") or 0)
        if not mime.startswith("audio/") or not audio_format or sample_rate <= 0:
            raise ValueError("audio_stream_start requires mime, format, and positive sample_rate")
        output.update({"mime": mime, "format": audio_format, "sample_rate": sample_rate})
        return output
    sequence = int(value.get("sequence") if value.get("sequence") is not None else -1)
    if sequence < 0:
        raise ValueError("audio stream sequence must be non-negative")
    output["sequence"] = sequence
    if event_type == AUDIO_STREAM_CHUNK:
        data = str(value.get("data") or "").strip()
        if not data:
            raise ValueError("audio_stream_chunk requires Base64 data")
        try:
            base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise ValueError("audio_stream_chunk data must be valid Base64") from exc
        output["data"] = data
    return output
