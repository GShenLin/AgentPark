"""Doubao section 1.3 asynchronous long-text TTS runtime."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime

from src.runtime_cancellation import sleep_with_cancel
from src.service_host import HostBoundService
from src.value_parsing import parse_optional_bool_value


class DoubaoTtsAsync(HostBoundService):
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
    def _positive(name: str, value: object, default: float) -> float:
        try:
            resolved = float(value if value not in (None, "") else default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive number.") from exc
        if resolved <= 0:
            raise ValueError(f"{name} must be a positive number.")
        return resolved

    def synthesize_tts_async(
        self,
        messages: object,
        *,
        tts_model: object = "seed-tts-2.0-standard",
        tts_speaker: object = "",
        tts_format: object = "mp3",
        tts_sample_rate: object = 24000,
        tts_bit_rate: object = 128000,
        tts_speech_rate: object = 0,
        tts_loudness_rate: object = 0,
        tts_enable_subtitle: object = False,
        tts_additions: object = "",
        tts_async_resource_id: object = "seed-tts-2.0",
        tts_async_poll_interval_seconds: object = 5,
        tts_async_poll_timeout_seconds: object = 3600,
        audio_filename_prefix: object = "generated_audio",
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        text = self._text(messages)
        if not text:
            raise ValueError("tts_async requires non-empty input text.")
        if len(text) > 100000:
            raise ValueError("tts_async input exceeds the documented 100000-character limit.")
        speaker = str(tts_speaker or "").strip()
        if not speaker:
            raise ValueError("tts_speaker is required for tts_async.")
        app_id = str(self.config.get("speechAppId") or "").strip()
        access_key = str(self.config.get("speechAccessKey") or "").strip()
        if not app_id or not access_key:
            raise ValueError("tts_async requires provider speechAppId and speechAccessKey as documented for this endpoint.")
        resource_id = str(tts_async_resource_id or "").strip()
        if not resource_id:
            raise ValueError("tts_async_resource_id is required.")
        fmt = str(tts_format or "mp3").strip().lower()
        if fmt not in {"mp3", "ogg_opus", "pcm", "wav"}:
            raise ValueError("tts_format is unsupported for tts_async.")
        audio_params = {
            "format": fmt,
            "sample_rate": int(tts_sample_rate),
            "speech_rate": int(tts_speech_rate),
            "loudness_rate": int(tts_loudness_rate),
            "enable_timestamp": bool(parse_optional_bool_value("tts_enable_subtitle", tts_enable_subtitle)),
        }
        if fmt == "mp3":
            audio_params["bit_rate"] = int(tts_bit_rate)
        req_params = {
            "text": text,
            "speaker": speaker,
            "model": str(tts_model or "").strip(),
            "audio_params": audio_params,
        }
        additions = self._json_object("tts_additions", tts_additions)
        if additions:
            req_params["additions"] = json.dumps(additions, ensure_ascii=False)
        request_id = str(uuid.uuid4())
        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Id": app_id,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
        }
        base = str(self.config.get("speechBaseUrl") or "https://openspeech.bytedance.com").rstrip("/")
        submit = self._post_json_with_retry(
            endpoint="tts/submit",
            url=f"{base}/api/v3/tts/submit",
            headers=headers,
            payload_json=json.dumps({
                "user": {"uid": app_id},
                "unique_id": request_id,
                "namespace": "BidirectionalTTS",
                "req_params": req_params,
            }, ensure_ascii=False),
            max_retries=int(self.config.get("maxRetries", 2)),
            retry_delay=float(self.config.get("retryDelaySec", 1)),
        )
        if not isinstance(submit, dict) or submit.get("code") != 20000000:
            raise ValueError(f"Doubao tts_async submit failed: {submit}")
        submit_data = submit.get("data")
        task_id = str(submit_data.get("task_id") or "").strip() if isinstance(submit_data, dict) else ""
        if not task_id:
            raise ValueError("Doubao tts_async submit response is missing task_id.")
        interval = self._positive("tts_async_poll_interval_seconds", tts_async_poll_interval_seconds, 5)
        timeout = self._positive("tts_async_poll_timeout_seconds", tts_async_poll_timeout_seconds, 3600)
        started = time.monotonic()
        while True:
            query = self._post_json_with_retry(
                endpoint="tts/query",
                url=f"{base}/api/v3/tts/query",
                headers=headers,
                payload_json=json.dumps({"task_id": task_id}),
                max_retries=int(self.config.get("maxRetries", 2)),
                retry_delay=float(self.config.get("retryDelaySec", 1)),
            )
            if not isinstance(query, dict) or query.get("code") != 20000000:
                raise ValueError(f"Doubao tts_async query failed: {query}")
            data = query.get("data")
            if not isinstance(data, dict):
                raise ValueError("Doubao tts_async query response is missing data.")
            status = int(data.get("task_status") or 0)
            if status == 2:
                audio_url = str(data.get("audio_url") or "").strip()
                if not audio_url:
                    raise ValueError("Doubao tts_async success response is missing audio_url.")
                audio = self._curl_get_bytes_with_retry(
                    url=audio_url,
                    max_retries=int(self.config.get("maxRetries", 2)),
                    retry_delay=float(self.config.get("retryDelaySec", 1)),
                )
                save_dir = os.path.dirname(self.current_memory_path)
                os.makedirs(save_dir, exist_ok=True)
                extension = "ogg" if fmt == "ogg_opus" else fmt
                prefix = str(audio_filename_prefix or "generated_audio").strip() or "generated_audio"
                path = os.path.join(save_dir, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{extension}")
                with open(path, "wb") as handle:
                    handle.write(audio)
                return {
                    "response": "Async TTS audio generated successfully.",
                    "audio_path": path,
                    "task_id": task_id,
                    "sentences": data.get("sentences") if isinstance(data.get("sentences"), list) else None,
                    "request_id": request_id,
                }
            if status == 3:
                raise ValueError(f"Doubao tts_async task failed: {query.get('message') or data}")
            if status != 1:
                raise ValueError(f"Doubao tts_async returned unsupported task_status: {status}")
            if time.monotonic() - started >= timeout:
                raise TimeoutError(f"Doubao tts_async timed out after {timeout:g}s. task_id={task_id}")
            sleep_with_cancel(interval, self._cancel_source())
