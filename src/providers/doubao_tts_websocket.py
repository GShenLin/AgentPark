"""Doubao sections 1.2.2 and 1.2.3 WebSocket TTS runtimes."""
from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime

from src.media_stream_protocol import build_audio_stream_chunk, build_audio_stream_end, build_audio_stream_start
from src.providers.doubao_speech_ws_protocol import (
    AUDIO_ONLY_SERVER,
    CONNECTION_FAILED,
    CONNECTION_FINISHED,
    CONNECTION_STARTED,
    ERROR_RESPONSE,
    FINISH_CONNECTION,
    FINISH_SESSION,
    FULL_SERVER_RESPONSE,
    SESSION_FAILED,
    SESSION_FINISHED,
    SESSION_STARTED,
    START_CONNECTION,
    START_SESSION,
    TASK_REQUEST,
    TTS_ENDED,
    TTS_RESPONSE,
    SpeechWsMessage,
    event_message,
    request_message,
)
from src.providers.provider_pressure import acquire_provider_pressure
from src.runtime_cancellation import raise_if_cancel_requested
from src.service_host import HostBoundService
from src.providers.doubao_speech_auth import require_doubao_x_api_key
from src.value_parsing import parse_optional_bool_value


_PATHS = {
    "tts_ws_unidirectional": "/api/v3/tts/unidirectional/stream",
    "tts_ws_bidirectional": "/api/v3/tts/bidirection",
}
_FORMATS = {"mp3": ("mp3", "audio/mpeg"), "pcm": ("pcm", "audio/L16"), "ogg_opus": ("ogg", "audio/ogg"), "wav": ("wav", "audio/wav")}


class DoubaoTtsWebSocket(HostBoundService):
    @staticmethod
    def _text(messages: object) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return "\n".join(
                    str(item.get("text") or "").strip()
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text") or "").strip()
                )
        return ""

    @staticmethod
    def _json_object(name: str, value: object) -> dict:
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return dict(value)
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} must be a JSON object.")
        return parsed

    @staticmethod
    def _json_strings(name: str, value: object) -> list[str]:
        if value in (None, ""):
            return []
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, list) or any(not isinstance(item, str) or not item.strip() for item in parsed):
            raise ValueError(f"{name} must be a JSON string array.")
        return [item.strip() for item in parsed]

    @staticmethod
    def _emit(host: object, event: dict) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if callable(callback):
            callback(event)

    @staticmethod
    def _ws_url(base: str, path: str) -> str:
        value = str(base or "https://openspeech.bytedance.com").rstrip("/")
        if value.startswith("https://"):
            value = "wss://" + value[8:]
        elif value.startswith("http://"):
            value = "ws://" + value[7:]
        if not value.startswith(("ws://", "wss://")):
            raise ValueError("speechBaseUrl must use http(s) or ws(s).")
        return value + path

    def synthesize_tts_websocket(
        self,
        messages: object,
        *,
        operation: str,
        tts_model: object = "seed-tts-2.0-standard",
        tts_speaker: object = "",
        tts_resource_id: object = "seed-tts-2.0",
        tts_format: object = "mp3",
        tts_sample_rate: object = 24000,
        tts_bit_rate: object = 128000,
        tts_speech_rate: object = 0,
        tts_loudness_rate: object = 0,
        tts_pitch: object = 0,
        tts_enable_subtitle: object = False,
        tts_aigc_watermark: object = False,
        tts_metadata_watermark: object = "",
        tts_ssml: object = "",
        tts_additions: object = "",
        tts_context_texts: object = "",
        tts_section_id: object = "",
        tts_tone_fidelity: object = False,
        audio_filename_prefix: object = "generated_audio",
    ) -> dict:
        if operation not in _PATHS:
            raise ValueError(f"Unsupported TTS WebSocket operation: {operation}")
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        text = self._text(messages)
        speaker = str(tts_speaker or "").strip()
        if not text or not speaker:
            raise ValueError(f"{operation} requires input text and tts_speaker.")
        api_key = require_doubao_x_api_key(self.config, operation)
        resource_id = str(tts_resource_id or "").strip()
        if not api_key or not resource_id:
            raise ValueError(f"{operation} requires API key and tts_resource_id.")
        fmt = str(tts_format or "mp3").strip().lower()
        if fmt not in _FORMATS:
            raise ValueError(f"Unsupported tts_format: {fmt}")
        sample_rate = int(tts_sample_rate)
        audio_params = {
            "format": fmt,
            "sample_rate": sample_rate,
            "speech_rate": int(tts_speech_rate),
            "loudness_rate": int(tts_loudness_rate),
            "enable_subtitle": bool(parse_optional_bool_value("tts_enable_subtitle", tts_enable_subtitle)),
        }
        if fmt == "mp3":
            audio_params["bit_rate"] = int(tts_bit_rate)
        req_params: dict = {"model": str(tts_model or "").strip(), "speaker": speaker, "audio_params": audio_params}
        if operation == "tts_ws_unidirectional":
            req_params["text"] = text
            ssml = str(tts_ssml or "").strip()
            if ssml:
                req_params["ssml"] = ssml
        additions = self._json_object("tts_additions", tts_additions)
        if bool(parse_optional_bool_value("tts_aigc_watermark", tts_aigc_watermark)):
            additions["aigc_watermark"] = True
        metadata = self._json_object("tts_metadata_watermark", tts_metadata_watermark)
        if metadata:
            additions["aigc_metadata"] = metadata
        if additions:
            req_params["additions"] = json.dumps(additions, ensure_ascii=False)
        context_texts = self._json_strings("tts_context_texts", tts_context_texts)
        if context_texts:
            req_params["context_texts"] = context_texts
        section_id = str(tts_section_id or "").strip()
        if section_id:
            req_params["section_id"] = section_id
        if operation == "tts_ws_unidirectional" and bool(parse_optional_bool_value("tts_tone_fidelity", tts_tone_fidelity)):
            req_params["tone_fidelity"] = True
        pitch = int(tts_pitch)
        if pitch:
            req_params["post_process"] = {"pitch": pitch}

        session_id = str(uuid.uuid4())
        headers = {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": session_id,
        }
        timeout = float(self.config.get("timeoutMs", 60000)) / 1000
        from websockets.sync.client import connect

        audio = bytearray()
        metadata_events: list[dict] = []
        sequence = 0
        ext, mime = _FORMATS[fmt]
        self._emit(self.host, build_audio_stream_start(stream_id=session_id, mime=mime, audio_format=fmt, sample_rate=sample_rate))
        with acquire_provider_pressure(self.host):
            connection = connect(
                self._ws_url(self.config.get("speechBaseUrl"), _PATHS[operation]),
                additional_headers=headers,
                open_timeout=min(10, timeout),
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            )
            try:
                if operation == "tts_ws_unidirectional":
                    connection.send(request_message(json.dumps({"req_params": req_params}, ensure_ascii=False).encode("utf-8")))
                else:
                    connection.send(event_message(START_CONNECTION))
                    sequence = self._receive_until(connection, timeout, {CONNECTION_STARTED}, audio, metadata_events, session_id, sequence)
                    connection.send(event_message(
                        START_SESSION,
                        json.dumps({"req_params": req_params}, ensure_ascii=False).encode("utf-8"),
                        session_id=session_id,
                    ))
                    sequence = self._receive_until(connection, timeout, {SESSION_STARTED}, audio, metadata_events, session_id, sequence)
                    connection.send(event_message(
                        TASK_REQUEST,
                        json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"),
                        session_id=session_id,
                    ))
                    connection.send(event_message(FINISH_SESSION, session_id=session_id))

                terminal = {SESSION_FINISHED, TTS_ENDED, CONNECTION_FINISHED}
                while True:
                    raise_if_cancel_requested(self._cancel_source())
                    message = self._recv(connection, timeout)
                    sequence = self._consume_message(message, audio, metadata_events, session_id, sequence)
                    if message.event in terminal or message.flag == 3:
                        break
                if operation == "tts_ws_bidirectional":
                    connection.send(event_message(FINISH_CONNECTION))
            finally:
                connection.close()
        if not audio:
            raise ValueError(f"Doubao {operation} completed without audio data.")
        self._emit(self.host, build_audio_stream_end(stream_id=session_id, sequence=sequence))
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        prefix = str(audio_filename_prefix or "generated_audio").strip() or "generated_audio"
        path = os.path.join(save_dir, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}")
        with open(path, "wb") as handle:
            handle.write(audio)
        return {
            "response": "WebSocket TTS audio generated successfully.",
            "audio_path": path,
            "stream_id": session_id,
            "events": metadata_events,
        }

    def _receive_until(self, connection, timeout: float, events: set[int], audio: bytearray, metadata: list[dict], stream_id: str, sequence: int) -> int:
        while True:
            message = self._recv(connection, timeout)
            sequence = self._consume_message(message, audio, metadata, stream_id, sequence)
            if message.event in events:
                return sequence

    @staticmethod
    def _recv(connection, timeout: float) -> SpeechWsMessage:
        raw = connection.recv(timeout=timeout)
        if not isinstance(raw, bytes):
            raise ValueError("Doubao TTS WebSocket returned a text frame.")
        return SpeechWsMessage.from_bytes(raw)

    def _consume_message(self, message: SpeechWsMessage, audio: bytearray, metadata: list[dict], stream_id: str, sequence: int) -> int:
        if message.message_type == ERROR_RESPONSE or message.event in {CONNECTION_FAILED, SESSION_FAILED}:
            raise ValueError(f"Doubao TTS WebSocket error {message.error_code}: {message.payload.decode('utf-8', 'replace')}")
        chunk = b""
        if message.message_type == AUDIO_ONLY_SERVER:
            chunk = message.payload
        elif message.message_type == FULL_SERVER_RESPONSE and message.payload:
            try:
                payload = json.loads(message.payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Doubao TTS WebSocket returned invalid JSON metadata.") from exc
            if isinstance(payload, dict):
                metadata.append(payload)
                encoded = payload.get("data") if message.event == TTS_RESPONSE else None
                if isinstance(encoded, str) and encoded:
                    chunk = base64.b64decode(encoded, validate=True)
        if chunk:
            audio.extend(chunk)
            for offset in range(0, len(chunk), 2048):
                self._emit(self.host, build_audio_stream_chunk(
                    stream_id=stream_id,
                    sequence=sequence,
                    data=chunk[offset:offset + 2048],
                ))
                sequence += 1
        return sequence
