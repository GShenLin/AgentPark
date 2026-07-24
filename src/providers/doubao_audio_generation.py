"""Doubao audio_generation SupportMode runtime.

This module implements section 1.1.1 of the supplied Doubao Speech API PDF:
``POST /api/v3/tts/create`` with ``X-Api-Key`` authentication.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime
from urllib.parse import urlparse

from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.doubao_speech_auth import require_doubao_x_api_key
from src.service_host import HostBoundService
from src.value_parsing import parse_optional_bool_value


_CREATE_URL = "https://openspeech.bytedance.com/api/v3/tts/create"
_SUPPORTED_FORMATS = {"wav": "wav", "mp3": "mp3", "pcm": "pcm", "ogg_opus": "ogg"}
_SUPPORTED_SAMPLE_RATES = {8000, 16000, 24000, 32000, 44100, 48000}
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".pcm", ".ogg", ".opus"}
_IMAGE_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp"}
_MAX_REFERENCE_BYTES = 10 * 1024 * 1024


class DoubaoAudioGeneration(ProviderRuntimeEventMixin, HostBoundService):
    @staticmethod
    def _create_url(config: dict) -> str:
        base = str(config.get("baseUrl") or "").strip().rstrip("/")
        if not base:
            return _CREATE_URL
        suffix = "/api/v3/tts/create"
        if base.endswith(suffix):
            return base
        return f"{base}{suffix}"

    @staticmethod
    def _prompt_and_message_references(messages: object) -> tuple[str, list[dict]]:
        if not isinstance(messages, list):
            return "", []
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content.strip(), []
            if not isinstance(content, list):
                continue
            texts: list[str] = []
            references: list[dict] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text = str(part.get("text") or "").strip()
                    if text:
                        texts.append(text)
                elif part.get("type") == "reference_resource":
                    references.append({
                        "kind": str(part.get("kind") or "").strip().lower(),
                        "uri": str(part.get("uri") or "").strip(),
                    })
            return "\n".join(texts).strip(), references
        return "", []

    @staticmethod
    def _bounded_int(name: str, value: object, *, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.") from exc
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return parsed

    @staticmethod
    def _parse_json_object(name: str, value: object) -> dict:
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return dict(value)
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a JSON object.")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} must be a JSON object.")
        return parsed

    @staticmethod
    def _configured_references(value: object) -> list[object]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return list(value)
        if not isinstance(value, str):
            raise ValueError("audio_references must be a list, JSON array, or newline-separated paths/URLs.")
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"audio_references must contain valid JSON: {exc}") from exc
            if not isinstance(parsed, list):
                raise ValueError("audio_references JSON must be an array.")
            return parsed
        return [line.strip() for line in text.splitlines() if line.strip()]

    @staticmethod
    def _reference_kind(uri: str, explicit_kind: str = "") -> str:
        if explicit_kind in {"audio", "image"}:
            return explicit_kind
        path = urlparse(uri).path if "://" in uri else uri
        ext = os.path.splitext(path)[1].lower()
        if ext in _AUDIO_EXTENSIONS:
            return "audio"
        if ext in _IMAGE_EXTENSIONS:
            return "image"
        raise ValueError(f"Cannot determine audio reference kind from: {uri}")

    @classmethod
    def _resource_reference(cls, item: object) -> dict:
        explicit_kind = ""
        if isinstance(item, dict) and "uri" in item:
            explicit_kind = str(item.get("kind") or "").strip().lower()
            item = item.get("uri")
        if isinstance(item, dict):
            allowed = {"speaker", "audio_data", "audio_url", "image_data", "image_url"}
            keys = [key for key in allowed if str(item.get(key) or "").strip()]
            if len(keys) != 1 or any(key not in allowed for key in item):
                raise ValueError("Each audio reference object must contain exactly one documented reference field.")
            return {keys[0]: item[keys[0]]}

        uri = str(item or "").strip()
        if not uri:
            raise ValueError("Audio reference paths and URLs must not be empty.")
        kind = cls._reference_kind(uri, explicit_kind)
        if uri.startswith(("http://", "https://")):
            return {f"{kind}_url": uri}
        if uri.startswith("asset://"):
            raise ValueError("asset:// audio references must be exposed as a public URL before provider submission.")

        path = uri[7:] if uri.startswith("file://") else uri
        if not os.path.isfile(path):
            raise ValueError(f"Audio reference file does not exist: {path}")
        size = os.path.getsize(path)
        if size > _MAX_REFERENCE_BYTES:
            raise ValueError(f"Audio reference exceeds the documented 10 MB limit: {path}")
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
        return {f"{kind}_data": encoded}

    @classmethod
    def _references(cls, speaker: object, configured: object, message_refs: list[dict]) -> list[dict]:
        raw = [*cls._configured_references(configured), *message_refs]
        speaker_id = str(speaker or "").strip()
        if speaker_id and raw:
            raise ValueError("audio_speaker is mutually exclusive with audio_references and input resources.")
        references = [{"speaker": speaker_id}] if speaker_id else [cls._resource_reference(item) for item in raw]
        audio_count = sum(any(key.startswith("audio_") or key == "speaker" for key in item) for item in references)
        image_count = sum(any(key.startswith("image_") for key in item) for item in references)
        if audio_count and image_count:
            raise ValueError("Audio and image references cannot be mixed in one audio generation request.")
        if audio_count > 3:
            raise ValueError("Audio generation accepts at most three audio references.")
        if image_count > 1:
            raise ValueError("Audio generation accepts at most one image reference.")
        return references

    def generate_audio(
        self,
        messages: object,
        *,
        audio_model: object = "seed-audio-1.0",
        audio_speaker: object = "",
        audio_references: object = "",
        audio_format: object = "mp3",
        audio_sample_rate: object = 48000,
        audio_speech_rate: object = 0,
        audio_loudness_rate: object = 0,
        audio_pitch_rate: object = 0,
        audio_enable_subtitle: object = False,
        audio_aigc_watermark: object = False,
        audio_metadata_watermark: object = "",
        audio_filename_prefix: object = "generated_audio",
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()

        prompt, message_refs = self._prompt_and_message_references(messages)
        if not prompt:
            raise ValueError("audio_generation requires a non-empty text prompt.")
        if len(prompt) > 3000:
            raise ValueError("audio_generation text_prompt exceeds the documented 3000-character limit.")

        model = str(audio_model or self.config.get("speechModel") or self.config.get("model") or "").strip()
        if not model:
            raise ValueError("audio_model is required.")
        fmt = str(audio_format or "wav").strip().lower()
        if fmt not in _SUPPORTED_FORMATS:
            raise ValueError(f"audio_format must be one of: {', '.join(sorted(_SUPPORTED_FORMATS))}.")
        sample_rate = self._bounded_int("audio_sample_rate", audio_sample_rate, minimum=8000, maximum=48000)
        if sample_rate not in _SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"Unsupported audio_sample_rate: {sample_rate}")

        audio_config = {
            "format": fmt,
            "sample_rate": sample_rate,
            "speech_rate": self._bounded_int("audio_speech_rate", audio_speech_rate, minimum=-50, maximum=100),
            "loudness_rate": self._bounded_int("audio_loudness_rate", audio_loudness_rate, minimum=-50, maximum=100),
            "pitch_rate": self._bounded_int("audio_pitch_rate", audio_pitch_rate, minimum=-12, maximum=12),
            "enable_subtitle": bool(parse_optional_bool_value("audio_enable_subtitle", audio_enable_subtitle)),
        }
        payload: dict = {"model": model, "text_prompt": prompt, "audio_config": audio_config}
        references = self._references(audio_speaker, audio_references, message_refs)
        if references:
            payload["references"] = references

        watermark: dict = {}
        if bool(parse_optional_bool_value("audio_aigc_watermark", audio_aigc_watermark)):
            watermark["aigc_watermark"] = True
        metadata_watermark = self._parse_json_object("audio_metadata_watermark", audio_metadata_watermark)
        if metadata_watermark:
            watermark["aigc_metadata"] = metadata_watermark
        if watermark:
            payload["watermark"] = watermark

        api_key = require_doubao_x_api_key(self.config, "Doubao audio_generation")
        request_id = str(uuid.uuid4())
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "X-Api-Request-Id": request_id,
        }
        self._emit_provider_runtime_notice(
            message=f"Generating audio with model {model}.",
            stage="audio_generation_start",
        )
        result = self._post_json_with_retry(
            endpoint="tts/create",
            url=self._create_url(self.config),
            headers=headers,
            payload_json=json.dumps(payload, ensure_ascii=False),
            max_retries=int(self.config.get("maxRetries", 2)),
            retry_delay=float(self.config.get("retryDelaySec", 1)),
        )
        if not isinstance(result, dict):
            raise ValueError("Doubao audio_generation returned a non-object response.")
        encoded_audio = result.get("audio")
        audio_url = str(result.get("url") or "").strip()
        if "code" in result and result.get("code") != 0:
            raise ValueError(f"Doubao audio_generation returned code {result.get('code')}: {result.get('message') or ''}")
        if not (isinstance(encoded_audio, str) and encoded_audio.strip()) and not audio_url:
            response_keys = ", ".join(sorted(str(key) for key in result)) or "<none>"
            raise ValueError(
                "Doubao audio_generation response contains neither audio nor url "
                f"(response keys: {response_keys})."
            )
        if isinstance(encoded_audio, str) and encoded_audio.strip():
            try:
                audio_bytes = base64.b64decode(encoded_audio, validate=True)
            except ValueError as exc:
                raise ValueError("Doubao audio_generation returned invalid Base64 audio.") from exc
        else:
            audio_bytes = self._curl_get_bytes_with_retry(
                url=audio_url,
                max_retries=int(self.config.get("maxRetries", 2)),
                retry_delay=float(self.config.get("retryDelaySec", 1)),
            )

        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        prefix = str(audio_filename_prefix or "generated_audio").strip() or "generated_audio"
        safe_prefix = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in prefix)
        agent_id = os.path.splitext(os.path.basename(self.current_memory_path))[0]
        if not safe_prefix.startswith(f"{agent_id}_"):
            safe_prefix = f"{agent_id}_{safe_prefix}"
        filename = f"{safe_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{_SUPPORTED_FORMATS[fmt]}"
        saved_path = os.path.join(save_dir, filename)
        with open(saved_path, "wb") as handle:
            handle.write(audio_bytes)

        response = {
            "response": str(result.get("message") or "Audio generated successfully."),
            "audio_path": saved_path,
            "model": model,
            "duration": result.get("duration"),
            "original_duration": result.get("original_duration"),
            "subtitle": result.get("subtitle") if isinstance(result.get("subtitle"), dict) else None,
            "request_id": request_id,
        }
        return {key: value for key, value in response.items() if value is not None}
