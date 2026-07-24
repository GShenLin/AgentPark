"""Doubao section 2.1 streaming ASR WebSocket runtime."""
from __future__ import annotations

import os
import uuid
import wave

from src.node_stream_protocol import build_node_message_delta
from src.providers.doubao_asr_ws_protocol import audio_request, full_request, parse_response
from src.providers.provider_pressure import acquire_provider_pressure
from src.runtime_cancellation import raise_if_cancel_requested, sleep_with_cancel
from src.service_host import HostBoundService
from src.providers.doubao_speech_auth import require_doubao_x_api_key
from src.value_parsing import parse_optional_bool_value


_PATHS = {
    "bidirectional": "/api/v3/sauc/bigmodel",
    "optimized": "/api/v3/sauc/bigmodel_async",
    "stream_input": "/api/v3/sauc/bigmodel_nostream",
}


class DoubaoAsrWebSocket(HostBoundService):
    @staticmethod
    def _message_audio(messages: object) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            for part in message.get("content") if isinstance(message.get("content"), list) else []:
                if isinstance(part, dict) and part.get("type") == "reference_resource" and part.get("kind") == "audio":
                    return str(part.get("uri") or "").strip()
        return ""

    @staticmethod
    def _local_audio(value: object) -> str:
        uri = str(value or "").strip()
        path = uri[7:] if uri.startswith("file://") else uri
        if uri.startswith(("http://", "https://", "asset://")) or not os.path.isfile(path):
            raise ValueError("asr_stream requires a local WAV/MP3/OGG audio attachment or path.")
        if os.path.splitext(path)[1].lower() not in {".wav", ".mp3", ".ogg", ".opus"}:
            raise ValueError("asr_stream supports WAV, MP3, and OGG Opus input.")
        return path

    @staticmethod
    def _audio_description(path: str) -> tuple[str, int, int, int]:
        extension = os.path.splitext(path)[1].lower()
        if extension == ".wav":
            with wave.open(path, "rb") as wav:
                return "wav", wav.getframerate(), wav.getsampwidth() * 8, wav.getnchannels()
        if extension in {".ogg", ".opus"}:
            return "ogg", 16000, 16, 1
        return "mp3", 16000, 16, 1

    @staticmethod
    def _emit_text(host: object, previous: str, current: str) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if not callable(callback) or current == previous:
            return
        delta = current[len(previous):] if current.startswith(previous) else current
        callback(build_node_message_delta(delta, current, force=not current.startswith(previous)))

    def recognize_asr_stream(
        self,
        messages: object,
        *,
        asr_source_audio: object = "",
        asr_stream_resource_id: object = "volc.seedasr.sauc.duration",
        asr_stream_endpoint_mode: object = "bidirectional",
        asr_stream_chunk_ms: object = 200,
        asr_uid: object = "",
        asr_model_name: object = "bigmodel",
        asr_enable_itn: object = True,
        asr_enable_punc: object = True,
        asr_enable_ddc: object = True,
        asr_enable_speaker_info: object = False,
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        api_key = require_doubao_x_api_key(self.config, "asr_stream")
        resource_id = str(asr_stream_resource_id or "").strip()
        if not api_key or not resource_id:
            raise ValueError("asr_stream requires API key and asr_stream_resource_id.")
        mode = str(asr_stream_endpoint_mode or "bidirectional").strip().lower()
        if mode not in _PATHS:
            raise ValueError(f"Unsupported asr_stream_endpoint_mode: {mode}")
        try:
            chunk_ms = int(asr_stream_chunk_ms)
        except (TypeError, ValueError) as exc:
            raise ValueError("asr_stream_chunk_ms must be 100-200.") from exc
        if chunk_ms < 100 or chunk_ms > 200:
            raise ValueError("asr_stream_chunk_ms must be 100-200.")
        path = self._local_audio(self._message_audio(messages) or asr_source_audio)
        audio_format, rate, bits, channels = self._audio_description(path)
        with open(path, "rb") as handle:
            audio_bytes = handle.read()
        if not audio_bytes:
            raise ValueError("asr_stream audio input is empty.")
        uid = str(asr_uid or self.config.get("speechAppId") or api_key).strip()
        request_payload = {
            "user": {"uid": uid},
            "audio": {"format": audio_format, "rate": rate, "bits": bits, "channel": channels},
            "request": {
                "model_name": str(asr_model_name or "bigmodel").strip() or "bigmodel",
                "enable_itn": bool(parse_optional_bool_value("asr_enable_itn", asr_enable_itn)),
                "enable_punc": bool(parse_optional_bool_value("asr_enable_punc", asr_enable_punc)),
                "enable_ddc": bool(parse_optional_bool_value("asr_enable_ddc", asr_enable_ddc)),
                "enable_speaker_info": bool(parse_optional_bool_value("asr_enable_speaker_info", asr_enable_speaker_info)),
                "show_utterances": True,
            },
        }
        connect_id = str(uuid.uuid4())
        base = str(self.config.get("speechBaseUrl") or "https://openspeech.bytedance.com").rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[8:]
        elif base.startswith("http://"):
            base = "ws://" + base[7:]
        timeout = float(self.config.get("timeoutMs", 60000)) / 1000
        from websockets.sync.client import connect

        chunk_bytes = max(1, int(rate * channels * (bits / 8) * chunk_ms / 1000))
        final_text = ""
        final_payload: dict = {}
        with acquire_provider_pressure(self.host):
            connection = connect(
                base + _PATHS[mode],
                additional_headers={
                    "X-Api-Key": api_key,
                    "X-Api-Resource-Id": resource_id,
                    "X-Api-Connect-Id": connect_id,
                },
                open_timeout=min(10, timeout),
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            )
            try:
                connection.send(full_request(request_payload))
                first = self._recv(connection, timeout)
                final_text, final_payload = self._consume_response(first, final_text, final_payload)
                chunks = [audio_bytes[offset:offset + chunk_bytes] for offset in range(0, len(audio_bytes), chunk_bytes)]
                for index, chunk in enumerate(chunks):
                    raise_if_cancel_requested(self._cancel_source())
                    final = index == len(chunks) - 1
                    connection.send(audio_request(chunk, final=final))
                    if mode == "bidirectional":
                        response = self._recv(connection, timeout)
                        previous = final_text
                        final_text, final_payload = self._consume_response(response, final_text, final_payload)
                        self._emit_text(self.host, previous, final_text)
                    if not final:
                        sleep_with_cancel(chunk_ms / 1000, self._cancel_source())
                if mode in {"optimized", "stream_input"}:
                    while True:
                        response = self._recv(connection, timeout)
                        previous = final_text
                        final_text, final_payload = self._consume_response(response, final_text, final_payload)
                        self._emit_text(self.host, previous, final_text)
                        if response.flag in {0x2, 0x3} or response.sequence < 0:
                            break
            finally:
                connection.close()
        if not final_text:
            raise ValueError("Doubao asr_stream completed without transcription text.")
        return {
            "response": final_text,
            "transcription": final_payload.get("result") if isinstance(final_payload.get("result"), dict) else final_payload,
            "audio_info": final_payload.get("audio_info") if isinstance(final_payload.get("audio_info"), dict) else None,
            "connect_id": connect_id,
        }

    @staticmethod
    def _recv(connection, timeout: float):
        raw = connection.recv(timeout=timeout)
        if not isinstance(raw, bytes):
            raise ValueError("Doubao ASR WebSocket returned a text frame.")
        return parse_response(raw)

    @staticmethod
    def _consume_response(response, current_text: str, current_payload: dict) -> tuple[str, dict]:
        if response.message_type == 0xF:
            raise ValueError(f"Doubao ASR WebSocket error {response.error_code}: {response.payload}")
        result = response.payload.get("result")
        text = str(result.get("text") or "").strip() if isinstance(result, dict) else ""
        return (text or current_text), (response.payload or current_payload)
