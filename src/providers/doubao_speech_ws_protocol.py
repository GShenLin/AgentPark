"""Minimal implementation of the official Doubao Speech WebSocket frame."""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass


FULL_CLIENT_REQUEST = 0x1
AUDIO_ONLY_CLIENT = 0x2
FULL_SERVER_RESPONSE = 0x9
AUDIO_ONLY_SERVER = 0xB
ERROR_RESPONSE = 0xF

NO_SEQUENCE = 0x0
POSITIVE_SEQUENCE = 0x1
NEGATIVE_SEQUENCE = 0x3
WITH_EVENT = 0x4

START_CONNECTION = 1
FINISH_CONNECTION = 2
CONNECTION_STARTED = 50
CONNECTION_FAILED = 51
CONNECTION_FINISHED = 52
START_SESSION = 100
CANCEL_SESSION = 101
FINISH_SESSION = 102
SESSION_STARTED = 150
SESSION_CANCELED = 151
SESSION_FINISHED = 152
SESSION_FAILED = 153
TASK_REQUEST = 200
TTS_SENTENCE_START = 350
TTS_SENTENCE_END = 351
TTS_RESPONSE = 352
TTS_ENDED = 359
TTS_SUBTITLE = 364


@dataclass(frozen=True)
class SpeechWsMessage:
    message_type: int
    flag: int = NO_SEQUENCE
    event: int = 0
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        output = io.BytesIO()
        output.write(bytes([0x11, (self.message_type << 4) | self.flag, 0x10, 0x00]))
        if self.flag == WITH_EVENT:
            output.write(struct.pack(">i", self.event))
            if self.event in {CONNECTION_STARTED, CONNECTION_FAILED, CONNECTION_FINISHED}:
                connection = self.connect_id.encode("utf-8")
                output.write(struct.pack(">I", len(connection)))
                output.write(connection)
            elif self.event not in {START_CONNECTION, FINISH_CONNECTION}:
                session = self.session_id.encode("utf-8")
                output.write(struct.pack(">I", len(session)))
                output.write(session)
        if self.message_type == ERROR_RESPONSE:
            output.write(struct.pack(">I", self.error_code))
        elif self.flag in {POSITIVE_SEQUENCE, NEGATIVE_SEQUENCE}:
            output.write(struct.pack(">i", self.sequence))
        output.write(struct.pack(">I", len(self.payload)))
        output.write(self.payload)
        return output.getvalue()

    @classmethod
    def from_bytes(cls, value: bytes) -> "SpeechWsMessage":
        if not isinstance(value, bytes) or len(value) < 8:
            raise ValueError("Doubao speech WebSocket frame is too short.")
        stream = io.BytesIO(value)
        version_header = stream.read(1)[0]
        if version_header >> 4 != 1:
            raise ValueError("Unsupported Doubao speech WebSocket protocol version.")
        header_words = version_header & 0x0F
        type_flag = stream.read(1)[0]
        message_type, flag = type_flag >> 4, type_flag & 0x0F
        stream.read(1)
        stream.read(max(0, header_words * 4 - 3))
        event = 0
        session_id = ""
        connect_id = ""
        sequence = 0
        error_code = 0
        if message_type == ERROR_RESPONSE:
            error_code = _read_int32(stream, signed=False)
        elif flag in {POSITIVE_SEQUENCE, NEGATIVE_SEQUENCE}:
            sequence = _read_int32(stream, signed=True)
        if flag == WITH_EVENT:
            event = _read_int32(stream, signed=True)
            if event not in {START_CONNECTION, FINISH_CONNECTION, CONNECTION_STARTED, CONNECTION_FAILED, CONNECTION_FINISHED}:
                session_id = _read_text(stream)
            if event in {CONNECTION_STARTED, CONNECTION_FAILED, CONNECTION_FINISHED}:
                connect_id = _read_text(stream)
        payload_size = _read_int32(stream, signed=False)
        payload = stream.read(payload_size)
        if len(payload) != payload_size or stream.read(1):
            raise ValueError("Malformed Doubao speech WebSocket payload length.")
        return cls(message_type, flag, event, session_id, connect_id, sequence, error_code, payload)


def event_message(event: int, payload: bytes = b"{}", *, session_id: str = "") -> bytes:
    return SpeechWsMessage(
        message_type=FULL_CLIENT_REQUEST,
        flag=WITH_EVENT,
        event=event,
        session_id=session_id,
        payload=payload,
    ).to_bytes()


def request_message(payload: bytes) -> bytes:
    return SpeechWsMessage(message_type=FULL_CLIENT_REQUEST, payload=payload).to_bytes()


def _read_int32(stream: io.BytesIO, *, signed: bool) -> int:
    value = stream.read(4)
    if len(value) != 4:
        raise ValueError("Truncated Doubao speech WebSocket frame.")
    return int.from_bytes(value, "big", signed=signed)


def _read_text(stream: io.BytesIO) -> str:
    size = _read_int32(stream, signed=False)
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("Truncated Doubao speech WebSocket text field.")
    return value.decode("utf-8")
