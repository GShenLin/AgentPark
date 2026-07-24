"""Doubao section 1.2.1 HTTP chunked text-to-speech runtime."""
from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime

from src.media_stream_protocol import (
    build_audio_stream_chunk,
    build_audio_stream_end,
    build_audio_stream_start,
)
from src.providers.curl_transport import CurlResponse
from src.service_host import HostBoundService
from src.providers.doubao_speech_auth import require_doubao_x_api_key
from src.value_parsing import parse_optional_bool_value


_ENDPOINT = "/api/v3/tts/unidirectional"
_FORMATS = {"mp3": ("mp3", "audio/mpeg"), "pcm": ("pcm", "audio/L16"), "ogg_opus": ("ogg", "audio/ogg"), "wav": ("wav", "audio/wav")}
_SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}
_PLAYBACK_CHUNK_BYTES = 2048


class DoubaoTtsHttp(HostBoundService):
    @staticmethod
    def _prompt(messages: object) -> str:
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
                    str(part.get("text") or "").strip()
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text" and str(part.get("text") or "").strip()
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
    def _json_string_list(name: str, value: object) -> list[str]:
        if value in (None, ""):
            return []
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} must be a JSON string array: {exc}") from exc
        if not isinstance(parsed, list) or any(not isinstance(item, str) or not item.strip() for item in parsed):
            raise ValueError(f"{name} must be a JSON array of non-empty strings.")
        return [item.strip() for item in parsed]

    @staticmethod
    def _integer(name: str, value: object, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be an integer.")
        try:
            resolved = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer.") from exc
        if resolved < minimum or resolved > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return resolved

    @staticmethod
    def _emit_audio_event(host: object, event: dict) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if callable(callback):
            callback(event)

    def synthesize_tts_http(
        self,
        messages: object,
        *,
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
        audio_filename_prefix: object = "generated_audio",
        tts_ssml: object = "",
        tts_additions: object = "",
        tts_context_texts: object = "",
        tts_section_id: object = "",
        tts_tone_fidelity: object = False,
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        text = self._prompt(messages)
        if not text:
            raise ValueError("tts_http requires non-empty input text.")
        speaker = str(tts_speaker or "").strip()
        if not speaker:
            raise ValueError("tts_speaker is required for tts_http.")
        model = str(tts_model or "").strip()
        resource_id = str(tts_resource_id or "").strip()
        if not resource_id:
            raise ValueError("tts_resource_id is required for tts_http.")
        fmt = str(tts_format or "mp3").strip().lower()
        if fmt not in _FORMATS:
            raise ValueError(f"tts_format must be one of: {', '.join(_FORMATS)}")
        sample_rate = self._integer("tts_sample_rate", tts_sample_rate, 8000, 48000)
        if sample_rate not in _SAMPLE_RATES:
            raise ValueError(f"Unsupported tts_sample_rate: {sample_rate}")
        bit_rate = self._integer("tts_bit_rate", tts_bit_rate, 64000, 160000)

        audio_params = {
            "format": fmt,
            "sample_rate": sample_rate,
            "speech_rate": self._integer("tts_speech_rate", tts_speech_rate, -50, 100),
            "loudness_rate": self._integer("tts_loudness_rate", tts_loudness_rate, -50, 100),
            "enable_subtitle": bool(parse_optional_bool_value("tts_enable_subtitle", tts_enable_subtitle)),
        }
        if fmt == "mp3":
            audio_params["bit_rate"] = bit_rate
        req_params: dict = {"text": text, "speaker": speaker, "audio_params": audio_params}
        if model:
            req_params["model"] = model
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
        context_texts = self._json_string_list("tts_context_texts", tts_context_texts)
        if context_texts:
            req_params["context_texts"] = context_texts
        section_id = str(tts_section_id or "").strip()
        if section_id:
            req_params["section_id"] = section_id
        if bool(parse_optional_bool_value("tts_tone_fidelity", tts_tone_fidelity)):
            req_params["tone_fidelity"] = True
        pitch = self._integer("tts_pitch", tts_pitch, -12, 12)
        if pitch:
            req_params["post_process"] = {"pitch": pitch}

        api_key = require_doubao_x_api_key(self.config, "tts_http")
        stream_id = str(uuid.uuid4())
        base = str(self.config.get("speechBaseUrl") or "https://openspeech.bytedance.com").rstrip("/")
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": stream_id,
        }
        ext, mime = _FORMATS[fmt]
        self._emit_audio_event(self.host, build_audio_stream_start(
            stream_id=stream_id,
            mime=mime,
            audio_format=fmt,
            sample_rate=sample_rate,
        ))
        audio = bytearray()
        sequence = 0
        sentence = None
        usage = None
        iterator = self._curl_post_sse_raw_lines(
            url=f"{base}{_ENDPOINT}",
            headers=headers,
            payload_json=json.dumps({"req_params": req_params}, ensure_ascii=False),
            timeout_sec=float(self.config.get("timeoutMs", 60000)) / 1000,
            marker="__DOUBAO_TTS_HTTP_CODE__:",
            yield_all_lines=True,
        )
        for item in iterator:
            if isinstance(item, CurlResponse):
                if item.status_code != 200:
                    raise ValueError(f"Doubao tts_http returned HTTP {item.status_code}: {item.body[-500:]}")
                continue
            try:
                event = json.loads(str(item))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Doubao tts_http returned invalid JSON chunk: {str(item)[:200]}") from exc
            if not isinstance(event, dict):
                raise ValueError("Doubao tts_http chunk must be a JSON object.")
            if event.get("code") != 0:
                raise ValueError(f"Doubao tts_http returned code {event.get('code')}: {event.get('message') or ''}")
            encoded = event.get("data")
            if isinstance(encoded, str) and encoded:
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise ValueError("Doubao tts_http returned invalid Base64 audio chunk.") from exc
                audio.extend(chunk)
                for offset in range(0, len(chunk), _PLAYBACK_CHUNK_BYTES):
                    self._emit_audio_event(self.host, build_audio_stream_chunk(
                        stream_id=stream_id,
                        sequence=sequence,
                        data=chunk[offset:offset + _PLAYBACK_CHUNK_BYTES],
                    ))
                    sequence += 1
            if isinstance(event.get("sentence"), dict):
                sentence = event["sentence"]
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
        if not audio:
            raise ValueError("Doubao tts_http completed without audio data.")
        self._emit_audio_event(self.host, build_audio_stream_end(stream_id=stream_id, sequence=sequence))

        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        prefix = str(audio_filename_prefix or "generated_audio").strip() or "generated_audio"
        safe_prefix = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in prefix)
        path = os.path.join(save_dir, f"{safe_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}")
        with open(path, "wb") as handle:
            handle.write(audio)
        return {
            "response": "TTS audio generated successfully.",
            "audio_path": path,
            "stream_id": stream_id,
            "sentence": sentence,
            "usage": usage,
        }
