"""Doubao section 3 end-to-end realtime dialogue runtime."""
from __future__ import annotations

import json
import os
import uuid
import wave
from datetime import datetime

from src.media_stream_protocol import build_audio_stream_chunk, build_audio_stream_end, build_audio_stream_start
from src.node_stream_protocol import build_node_message_delta
from src.providers.doubao_speech_ws_protocol import (
    AUDIO_ONLY_CLIENT,
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
    WITH_EVENT,
    SpeechWsMessage,
    event_message,
)
from src.providers.provider_pressure import acquire_provider_pressure
from src.runtime_cancellation import raise_if_cancel_requested, sleep_with_cancel
from src.service_host import HostBoundService
from src.value_parsing import parse_optional_bool_value


ASR_RESPONSE = 451
CHAT_RESPONSE = 550
CHAT_ENDED = 559
CHAT_TEXT_QUERY = 501
DIALOG_COMMON_ERROR = 599


class DoubaoRealtimeDialogue(HostBoundService):
    @staticmethod
    def _message_text(messages: object) -> str:
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
    def _message_audio(messages: object) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get("type") == "reference_resource" and item.get("kind") == "audio":
                    return str(item.get("uri") or "").strip()
        return ""

    @staticmethod
    def _local_pcm_wav(value: object) -> tuple[str, bytes]:
        uri = str(value or "").strip()
        path = uri[7:] if uri.startswith("file://") else uri
        if uri.startswith(("http://", "https://", "asset://")) or not os.path.isfile(path):
            raise ValueError("realtime audio_file mode requires a local WAV attachment or path.")
        if os.path.splitext(path)[1].lower() != ".wav":
            raise ValueError("realtime audio_file mode requires WAV input.")
        with wave.open(path, "rb") as source:
            if source.getframerate() != 16000 or source.getsampwidth() != 2 or source.getnchannels() != 1:
                raise ValueError("realtime WAV input must be 16 kHz, 16-bit, mono PCM.")
            frames = source.readframes(source.getnframes())
        if not frames:
            raise ValueError("realtime WAV input is empty.")
        return path, frames

    @staticmethod
    def _ws_url(base: object) -> str:
        value = str(base or "https://openspeech.bytedance.com").rstrip("/")
        if value.startswith("https://"):
            value = "wss://" + value[8:]
        elif value.startswith("http://"):
            value = "ws://" + value[7:]
        if not value.startswith(("ws://", "wss://")):
            raise ValueError("speechBaseUrl must use http(s) or ws(s).")
        return value + "/api/v3/realtime/dialogue"

    @staticmethod
    def _emit(host: object, event: dict) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if callable(callback):
            callback(event)

    def run_realtime_dialogue(
        self,
        messages: object,
        *,
        realtime_input_mode: object = "audio_file",
        realtime_source_audio: object = "",
        realtime_text: object = "",
        realtime_model: object = "2.2.0.0",
        realtime_speaker: object = "",
        realtime_bot_name: object = "",
        realtime_system_role: object = "",
        realtime_speaking_style: object = "",
        realtime_character_manifest: object = "",
        realtime_strict_audit: object = True,
        realtime_speech_rate: object = 0,
        realtime_loudness_rate: object = 0,
        realtime_resource_id: object = "volc.speech.dialog",
        realtime_chunk_ms: object = 20,
        audio_filename_prefix: object = "realtime_dialogue",
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        app_id = str(self.config.get("speechAppId") or "").strip()
        access_key = str(self.config.get("speechAccessKey") or "").strip()
        if not app_id or not access_key:
            raise ValueError("realtime requires provider speechAppId and speechAccessKey as documented for the legacy endpoint.")
        input_mode = str(realtime_input_mode or "audio_file").strip().lower()
        if input_mode not in {"audio_file", "text"}:
            raise ValueError("realtime_input_mode must be audio_file or text.")
        model = str(realtime_model or "").strip()
        if model not in {"1.2.1.1", "2.2.0.0"}:
            raise ValueError("realtime_model must be 1.2.1.1 or 2.2.0.0.")
        chunk_ms = int(realtime_chunk_ms)
        if chunk_ms != 20:
            raise ValueError("realtime_chunk_ms must be 20 as recommended by the official protocol.")
        pcm = b""
        text_input = ""
        if input_mode == "audio_file":
            _, pcm = self._local_pcm_wav(self._message_audio(messages) or realtime_source_audio)
        else:
            text_input = str(realtime_text or self._message_text(messages)).strip()
            if not text_input:
                raise ValueError("realtime text mode requires realtime_text or input text.")

        dialog_extra = {
            "input_mod": input_mode,
            "strict_audit": bool(parse_optional_bool_value("realtime_strict_audit", realtime_strict_audit)),
            "model": model,
        }
        dialog: dict = {"extra": dialog_extra}
        for key, value in (
            ("bot_name", realtime_bot_name),
            ("system_role", realtime_system_role),
            ("speaking_style", realtime_speaking_style),
            ("character_manifest", realtime_character_manifest),
        ):
            resolved = str(value or "").strip()
            if resolved:
                dialog[key] = resolved
        tts: dict = {
            "extra": {},
            "audio_config": {
                "speech_rate": int(realtime_speech_rate),
                "loudness_rate": int(realtime_loudness_rate),
            },
        }
        speaker = str(realtime_speaker or "").strip()
        if speaker:
            tts["speaker"] = speaker
        start_payload = {"asr": {"extra": {}}, "dialog": dialog, "tts": tts}

        session_id = str(uuid.uuid4())
        connect_id = str(uuid.uuid4())
        resource_id = str(realtime_resource_id or "").strip()
        if not resource_id:
            raise ValueError("realtime_resource_id is required.")
        headers = {
            "X-Api-App-ID": app_id,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
            "X-Api-Connect-Id": connect_id,
        }
        timeout = float(self.config.get("timeoutMs", 60000)) / 1000
        from websockets.sync.client import connect

        audio = bytearray()
        metadata: list[dict] = []
        response_text = ""
        transcription = ""
        sequence = 0
        self._emit(self.host, build_audio_stream_start(
            stream_id=session_id, mime="audio/ogg", audio_format="ogg_opus", sample_rate=24000,
        ))
        with acquire_provider_pressure(self.host):
            connection = connect(
                self._ws_url(self.config.get("speechBaseUrl")),
                additional_headers=headers,
                open_timeout=min(10, timeout),
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            )
            try:
                connection.send(event_message(START_CONNECTION))
                self._receive_until(connection, timeout, {CONNECTION_STARTED})
                connection.send(event_message(
                    START_SESSION,
                    json.dumps(start_payload, ensure_ascii=False).encode("utf-8"),
                    session_id=session_id,
                ))
                self._receive_until(connection, timeout, {SESSION_STARTED})
                if input_mode == "audio_file":
                    chunk_size = 16000 * 2 * chunk_ms // 1000
                    chunks = [pcm[offset:offset + chunk_size] for offset in range(0, len(pcm), chunk_size)]
                    for index, chunk in enumerate(chunks):
                        raise_if_cancel_requested(self._cancel_source())
                        connection.send(SpeechWsMessage(
                            message_type=AUDIO_ONLY_CLIENT,
                            flag=WITH_EVENT,
                            event=TASK_REQUEST,
                            session_id=session_id,
                            payload=chunk,
                        ).to_bytes())
                        if index < len(chunks) - 1:
                            sleep_with_cancel(chunk_ms / 1000, self._cancel_source())
                else:
                    connection.send(event_message(
                        CHAT_TEXT_QUERY,
                        json.dumps({"content": text_input}, ensure_ascii=False).encode("utf-8"),
                        session_id=session_id,
                    ))

                while True:
                    raise_if_cancel_requested(self._cancel_source())
                    message = self._recv(connection, timeout)
                    payload = self._json_payload(message)
                    if message.message_type == ERROR_RESPONSE or message.event in {CONNECTION_FAILED, SESSION_FAILED, DIALOG_COMMON_ERROR}:
                        raise ValueError(
                            f"Doubao realtime dialogue error {message.error_code}: "
                            f"{message.payload.decode('utf-8', 'replace')}"
                        )
                    if message.event == TTS_RESPONSE or message.message_type == AUDIO_ONLY_SERVER:
                        chunk = message.payload
                        audio.extend(chunk)
                        for offset in range(0, len(chunk), 2048):
                            self._emit(self.host, build_audio_stream_chunk(
                                stream_id=session_id,
                                sequence=sequence,
                                data=chunk[offset:offset + 2048],
                            ))
                            sequence += 1
                    elif payload:
                        metadata.append({"event": message.event, **payload})
                        if message.event == CHAT_RESPONSE:
                            previous = response_text
                            response_text = str(payload.get("content") or response_text).strip()
                            self._emit_text(self.host, previous, response_text)
                        elif message.event == ASR_RESPONSE:
                            results = payload.get("results")
                            if isinstance(results, list):
                                transcription = "".join(
                                    str(item.get("text") or "") for item in results if isinstance(item, dict)
                                ).strip() or transcription
                    if message.event == TTS_ENDED:
                        break

                connection.send(event_message(FINISH_SESSION, session_id=session_id))
                self._receive_until(connection, timeout, {SESSION_FINISHED})
                connection.send(event_message(FINISH_CONNECTION))
                self._receive_until(connection, timeout, {CONNECTION_FINISHED})
            finally:
                connection.close()
        if not audio:
            raise ValueError("Doubao realtime dialogue completed without audio data.")
        self._emit(self.host, build_audio_stream_end(stream_id=session_id, sequence=sequence))
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        prefix = str(audio_filename_prefix or "realtime_dialogue").strip() or "realtime_dialogue"
        path = os.path.join(save_dir, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.ogg")
        with open(path, "wb") as handle:
            handle.write(audio)
        return {
            "response": response_text or "Realtime dialogue audio generated successfully.",
            "audio_path": path,
            "transcription": transcription,
            "stream_id": session_id,
            "events": metadata,
        }

    def _receive_until(self, connection, timeout: float, events: set[int]) -> None:
        while True:
            message = self._recv(connection, timeout)
            if message.message_type == ERROR_RESPONSE or message.event in {CONNECTION_FAILED, SESSION_FAILED}:
                raise ValueError(
                    f"Doubao realtime dialogue handshake error {message.error_code}: "
                    f"{message.payload.decode('utf-8', 'replace')}"
                )
            if message.event in events:
                return

    @staticmethod
    def _recv(connection, timeout: float) -> SpeechWsMessage:
        raw = connection.recv(timeout=timeout)
        if not isinstance(raw, bytes):
            raise ValueError("Doubao realtime dialogue returned a text frame.")
        return SpeechWsMessage.from_bytes(raw)

    @staticmethod
    def _json_payload(message: SpeechWsMessage) -> dict:
        if not message.payload or message.message_type == AUDIO_ONLY_SERVER or message.event == TTS_RESPONSE:
            return {}
        try:
            value = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Doubao realtime dialogue returned invalid JSON metadata.") from exc
        if not isinstance(value, dict):
            raise ValueError("Doubao realtime dialogue metadata must be a JSON object.")
        return value

    @staticmethod
    def _emit_text(host: object, previous: str, current: str) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if not callable(callback) or current == previous:
            return
        extends = current.startswith(previous)
        callback(build_node_message_delta(
            current[len(previous):] if extends else current,
            current,
            force=not extends,
        ))
