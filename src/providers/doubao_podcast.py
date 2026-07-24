"""Doubao section 4 podcast WebSocket runtime."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from src.media_stream_protocol import build_audio_stream_chunk, build_audio_stream_end, build_audio_stream_start
from src.providers.doubao_speech_ws_protocol import (
    AUDIO_ONLY_SERVER,
    CONNECTION_FINISHED,
    ERROR_RESPONSE,
    FINISH_CONNECTION,
    SESSION_FAILED,
    SESSION_FINISHED,
    SESSION_STARTED,
    START_SESSION,
    SpeechWsMessage,
    event_message,
)
from src.providers.provider_pressure import acquire_provider_pressure
from src.runtime_cancellation import raise_if_cancel_requested
from src.service_host import HostBoundService
from src.value_parsing import parse_optional_bool_value


PODCAST_ROUND_START = 360
PODCAST_ROUND_RESPONSE = 361
PODCAST_ROUND_END = 362
PODCAST_END = 363
USAGE_RESPONSE = 154
_FORMATS = {
    "mp3": ("mp3", "audio/mpeg"),
    "ogg_opus": ("ogg", "audio/ogg"),
    "pcm": ("pcm", "audio/L16"),
    "aac": ("aac", "audio/aac"),
}


class DoubaoPodcast(HostBoundService):
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
    def _json_list(name: str, value: object) -> list:
        if value in (None, ""):
            return []
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"{name} must be a JSON array.")
        return parsed

    @staticmethod
    def _emit(host: object, event: dict) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if callable(callback):
            callback(event)

    @staticmethod
    def _ws_url(base: object) -> str:
        value = str(base or "https://openspeech.bytedance.com").rstrip("/")
        if value.startswith("https://"):
            value = "wss://" + value[8:]
        elif value.startswith("http://"):
            value = "ws://" + value[7:]
        if not value.startswith(("ws://", "wss://")):
            raise ValueError("speechBaseUrl must use http(s) or ws(s).")
        return value + "/api/v3/sami/podcasttts"

    def generate_podcast(
        self,
        messages: object,
        *,
        podcast_action: object = 0,
        podcast_input_text: object = "",
        podcast_input_url: object = "",
        podcast_prompt_text: object = "",
        podcast_nlp_texts: object = "",
        podcast_speakers: object = "",
        podcast_random_speaker_order: object = True,
        podcast_format: object = "mp3",
        podcast_sample_rate: object = 24000,
        podcast_speech_rate: object = 0,
        podcast_use_head_music: object = True,
        podcast_use_tail_music: object = False,
        podcast_return_audio_url: object = True,
        podcast_strict_audit: object = False,
        podcast_input_text_max_length: object = "",
        podcast_resource_id: object = "volc.service_type.10050",
        audio_filename_prefix: object = "generated_podcast",
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        app_id = str(self.config.get("speechAppId") or "").strip()
        access_key = str(self.config.get("speechAccessKey") or "").strip()
        if not app_id or not access_key:
            raise ValueError("podcast requires provider speechAppId and speechAccessKey as documented for the legacy endpoint.")
        try:
            action = int(podcast_action)
        except (TypeError, ValueError) as exc:
            raise ValueError("podcast_action must be 0, 3, or 4.") from exc
        if action not in {0, 3, 4}:
            raise ValueError("podcast_action must be 0, 3, or 4.")
        fmt = str(podcast_format or "mp3").strip().lower()
        if fmt not in _FORMATS:
            raise ValueError(f"Unsupported podcast_format: {fmt}")
        sample_rate = int(podcast_sample_rate)
        if sample_rate not in {16000, 24000, 48000}:
            raise ValueError("podcast_sample_rate must be 16000, 24000, or 48000.")
        payload: dict = {
            "input_id": str(uuid.uuid4()),
            "action": action,
            "use_head_music": bool(parse_optional_bool_value("podcast_use_head_music", podcast_use_head_music)),
            "use_tail_music": bool(parse_optional_bool_value("podcast_use_tail_music", podcast_use_tail_music)),
            "audio_config": {
                "format": fmt,
                "sample_rate": sample_rate,
                "speech_rate": int(podcast_speech_rate),
            },
        }
        if action == 0:
            text = str(podcast_input_text or self._text(messages)).strip()
            input_url = str(podcast_input_url or "").strip()
            if not text and not input_url:
                raise ValueError("podcast action 0 requires input text or podcast_input_url.")
            if text:
                payload["input_text"] = text
            input_info: dict = {
                "return_audio_url": bool(parse_optional_bool_value(
                    "podcast_return_audio_url", podcast_return_audio_url,
                )),
                "strict_audit": bool(parse_optional_bool_value("podcast_strict_audit", podcast_strict_audit)),
            }
            if input_url:
                if not input_url.startswith(("http://", "https://")):
                    raise ValueError("podcast_input_url must be a public HTTP(S) URL.")
                input_info["input_url"] = input_url
            if podcast_input_text_max_length not in (None, ""):
                input_info["input_text_max_length"] = int(podcast_input_text_max_length)
            payload["input_info"] = input_info
        elif action == 3:
            rounds = self._json_list("podcast_nlp_texts", podcast_nlp_texts)
            if not rounds or any(
                not isinstance(item, dict)
                or not str(item.get("text") or "").strip()
                or not str(item.get("speaker") or "").strip()
                for item in rounds
            ):
                raise ValueError("podcast_nlp_texts must contain objects with non-empty text and speaker.")
            payload["nlp_texts"] = rounds
        else:
            prompt = str(podcast_prompt_text or self._text(messages)).strip()
            if not prompt:
                raise ValueError("podcast action 4 requires podcast_prompt_text or input text.")
            payload["prompt_text"] = prompt
            payload["input_info"] = {
                "return_audio_url": bool(parse_optional_bool_value(
                    "podcast_return_audio_url", podcast_return_audio_url,
                )),
                "strict_audit": bool(parse_optional_bool_value("podcast_strict_audit", podcast_strict_audit)),
            }
        speakers = self._json_list("podcast_speakers", podcast_speakers)
        if speakers:
            if len(speakers) != 2 or any(not isinstance(item, str) or not item.strip() for item in speakers):
                raise ValueError("podcast_speakers must contain exactly two speaker ids.")
            payload["speaker_info"] = {
                "random_order": bool(parse_optional_bool_value(
                    "podcast_random_speaker_order", podcast_random_speaker_order,
                )),
                "speakers": [item.strip() for item in speakers],
            }

        session_id = str(uuid.uuid4())
        resource_id = str(podcast_resource_id or "").strip()
        if not resource_id:
            raise ValueError("podcast_resource_id is required.")
        headers = {
            "X-Api-App-Id": app_id,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-App-Key": "aGjiRDfUWi",
            "X-Api-Request-Id": session_id,
        }
        timeout = float(self.config.get("timeoutMs", 60000)) / 1000
        from websockets.sync.client import connect

        audio = bytearray()
        metadata: list[dict] = []
        sequence = 0
        ext, mime = _FORMATS[fmt]
        self._emit(self.host, build_audio_stream_start(
            stream_id=session_id, mime=mime, audio_format=fmt, sample_rate=sample_rate,
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
                connection.send(event_message(
                    START_SESSION,
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    session_id=session_id,
                ))
                while True:
                    raise_if_cancel_requested(self._cancel_source())
                    message = self._recv(connection, timeout)
                    if message.message_type == ERROR_RESPONSE or message.event == SESSION_FAILED:
                        raise ValueError(
                            f"Doubao podcast WebSocket error {message.error_code}: "
                            f"{message.payload.decode('utf-8', 'replace')}"
                        )
                    if message.event == PODCAST_ROUND_RESPONSE or message.message_type == AUDIO_ONLY_SERVER:
                        chunk = message.payload
                        audio.extend(chunk)
                        for offset in range(0, len(chunk), 2048):
                            self._emit(self.host, build_audio_stream_chunk(
                                stream_id=session_id,
                                sequence=sequence,
                                data=chunk[offset:offset + 2048],
                            ))
                            sequence += 1
                    elif message.payload:
                        try:
                            item = json.loads(message.payload.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            raise ValueError("Doubao podcast returned invalid JSON metadata.") from exc
                        if isinstance(item, dict):
                            metadata.append({"event": message.event, **item})
                    if message.event == SESSION_FINISHED:
                        break
                connection.send(event_message(FINISH_CONNECTION))
                while True:
                    message = self._recv(connection, timeout)
                    if message.message_type == ERROR_RESPONSE:
                        raise ValueError(
                            f"Doubao podcast connection finish failed {message.error_code}: "
                            f"{message.payload.decode('utf-8', 'replace')}"
                        )
                    if message.event == CONNECTION_FINISHED:
                        break
            finally:
                connection.close()
        if not audio:
            raise ValueError("Doubao podcast completed without audio data.")
        self._emit(self.host, build_audio_stream_end(stream_id=session_id, sequence=sequence))
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        prefix = str(audio_filename_prefix or "generated_podcast").strip() or "generated_podcast"
        path = os.path.join(save_dir, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}")
        with open(path, "wb") as handle:
            handle.write(audio)
        podcast_end = next((item for item in reversed(metadata) if item.get("event") == PODCAST_END), {})
        return {
            "response": "Podcast audio generated successfully.",
            "audio_path": path,
            "stream_id": session_id,
            "podcast": podcast_end.get("meta_info") if isinstance(podcast_end.get("meta_info"), dict) else {},
            "events": metadata,
        }

    @staticmethod
    def _recv(connection, timeout: float) -> SpeechWsMessage:
        raw = connection.recv(timeout=timeout)
        if not isinstance(raw, bytes):
            raise ValueError("Doubao podcast WebSocket returned a text frame.")
        return SpeechWsMessage.from_bytes(raw)
