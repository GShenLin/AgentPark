"""Binary frame codec for Doubao streaming ASR WebSocket."""
from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class AsrWsResponse:
    message_type: int
    flag: int
    sequence: int
    error_code: int
    payload: dict


def full_request(payload: dict) -> bytes:
    data = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return bytes([0x11, 0x10, 0x11, 0x00]) + struct.pack(">I", len(data)) + data


def audio_request(data: bytes, *, final: bool) -> bytes:
    payload = gzip.compress(data)
    flag = 0x2 if final else 0x0
    return bytes([0x11, (0x2 << 4) | flag, 0x01, 0x00]) + struct.pack(">I", len(payload)) + payload


def parse_response(value: bytes) -> AsrWsResponse:
    if not isinstance(value, bytes) or len(value) < 8:
        raise ValueError("Doubao ASR WebSocket frame is too short.")
    version_header, type_flag, serialization_compression, _reserved = value[:4]
    if version_header >> 4 != 1:
        raise ValueError("Unsupported Doubao ASR WebSocket protocol version.")
    header_size = (version_header & 0x0F) * 4
    message_type, flag = type_flag >> 4, type_flag & 0x0F
    compression = serialization_compression & 0x0F
    offset = header_size
    sequence = 0
    error_code = 0
    if message_type == 0xF:
        error_code = struct.unpack(">I", value[offset:offset + 4])[0]
        offset += 4
    elif flag in {0x1, 0x3}:
        sequence = struct.unpack(">i", value[offset:offset + 4])[0]
        offset += 4
    if len(value) < offset + 4:
        raise ValueError("Truncated Doubao ASR WebSocket payload size.")
    size = struct.unpack(">I", value[offset:offset + 4])[0]
    offset += 4
    payload_bytes = value[offset:offset + size]
    if len(payload_bytes) != size or offset + size != len(value):
        raise ValueError("Malformed Doubao ASR WebSocket payload length.")
    if compression == 1:
        payload_bytes = gzip.decompress(payload_bytes)
    try:
        payload = json.loads(payload_bytes.decode("utf-8")) if payload_bytes else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Doubao ASR WebSocket returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Doubao ASR WebSocket response payload must be an object.")
    return AsrWsResponse(message_type, flag, sequence, error_code, payload)
