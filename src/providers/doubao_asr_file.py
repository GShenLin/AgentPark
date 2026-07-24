"""Doubao recording-file ASR standard and idle submit/query runtimes."""
from __future__ import annotations

import json
import os
import time
import uuid
from urllib.parse import urlparse

from src.service_host import HostBoundService
from src.providers.doubao_speech_auth import require_doubao_x_api_key
from src.runtime_cancellation import sleep_with_cancel
from src.value_parsing import parse_optional_bool_value


_ENDPOINTS = {
    "asr_standard": ("/api/v3/auc/bigmodel/submit", "/api/v3/auc/bigmodel/query"),
    "asr_idle": ("/api/v3/auc/bigmodel/idle/submit", "/api/v3/auc/bigmodel/idle/query"),
}
_PENDING_CODES = {"20000001", "20000002"}


class DoubaoAsrFile(HostBoundService):
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
    def _public_audio_url(value: object) -> str:
        uri = str(value or "").strip()
        if not uri.startswith(("http://", "https://")):
            raise ValueError("asr_standard/asr_idle require a public HTTP(S) audio URL; use asr_flash for a local recording.")
        return uri

    @staticmethod
    def _infer_format(url: str, explicit: object) -> str:
        value = str(explicit or "").strip().lower()
        if value:
            return value
        ext = os.path.splitext(urlparse(url).path)[1].lower().lstrip(".")
        if ext == "opus":
            return "ogg"
        if ext in {"wav", "mp3", "ogg"}:
            return ext
        raise ValueError("asr_audio_format is required when the public audio URL has no supported extension.")

    @staticmethod
    def _positive_number(name: str, value: object, default: float) -> float:
        try:
            resolved = float(value if value not in (None, "") else default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive number.") from exc
        if resolved <= 0:
            raise ValueError(f"{name} must be a positive number.")
        return resolved

    def _headers(self, *, operation: str, api_key: str, resource_id: str, request_id: str, sequence: bool, log_id: str = "") -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
        }
        if sequence:
            headers["X-Api-Sequence"] = "-1"
        if log_id:
            headers["X-Tt-Logid"] = log_id
        if operation == "asr_idle":
            app_id = str(self.config.get("speechAppId") or "").strip()
            access_key = str(self.config.get("speechAccessKey") or "").strip()
            if not app_id or not access_key:
                raise ValueError("asr_idle requires provider speechAppId and speechAccessKey as documented for the legacy endpoint.")
            headers["X-Api-App-Key"] = app_id
            headers["X-Api-Access-Key"] = access_key
        else:
            headers["X-Api-Key"] = api_key
        return headers

    def recognize_asr_file(
        self,
        messages: object,
        *,
        operation: str,
        asr_source_audio: object = "",
        asr_standard_resource_id: object = "volc.seedasr.auc",
        asr_idle_resource_id: object = "volc.bigasr.auc_idle",
        asr_uid: object = "",
        asr_model_name: object = "bigmodel",
        asr_language: object = "",
        asr_audio_format: object = "",
        asr_audio_codec: object = "raw",
        asr_audio_rate: object = 16000,
        asr_audio_bits: object = 16,
        asr_audio_channel: object = 1,
        asr_enable_itn: object = True,
        asr_enable_punc: object = True,
        asr_enable_ddc: object = True,
        asr_enable_speaker_info: object = False,
        asr_show_utterances: object = True,
        asr_enable_channel_split: object = False,
        asr_poll_interval_seconds: object = 5,
        asr_poll_timeout_seconds: object = 3600,
    ) -> dict:
        if operation not in _ENDPOINTS:
            raise ValueError(f"Unsupported ASR file operation: {operation}")
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        api_key = "" if operation == "asr_idle" else require_doubao_x_api_key(self.config, operation)
        audio_url = self._public_audio_url(self._message_audio(messages) or asr_source_audio)
        resource_id = str(asr_idle_resource_id if operation == "asr_idle" else asr_standard_resource_id).strip()
        if not resource_id:
            raise ValueError(f"{operation} resource id is required.")
        uid = str(asr_uid or self.config.get("speechAppId") or api_key).strip()
        audio = {
            "url": audio_url,
            "format": self._infer_format(audio_url, asr_audio_format),
            "codec": str(asr_audio_codec or "raw").strip() or "raw",
            "rate": int(asr_audio_rate),
            "bits": int(asr_audio_bits),
            "channel": int(asr_audio_channel),
        }
        language = str(asr_language or "").strip()
        if language:
            audio["language"] = language
        request = {
            "model_name": str(asr_model_name or "bigmodel").strip() or "bigmodel",
            "enable_itn": bool(parse_optional_bool_value("asr_enable_itn", asr_enable_itn)),
            "enable_punc": bool(parse_optional_bool_value("asr_enable_punc", asr_enable_punc)),
            "enable_ddc": bool(parse_optional_bool_value("asr_enable_ddc", asr_enable_ddc)),
            "enable_speaker_info": bool(parse_optional_bool_value("asr_enable_speaker_info", asr_enable_speaker_info)),
            "show_utterances": bool(parse_optional_bool_value("asr_show_utterances", asr_show_utterances)),
            "enable_channel_split": bool(parse_optional_bool_value("asr_enable_channel_split", asr_enable_channel_split)),
        }
        request_id = str(uuid.uuid4())
        base = str(self.config.get("speechBaseUrl") or "https://openspeech.bytedance.com").rstrip("/")
        submit_path, query_path = _ENDPOINTS[operation]
        timeout = float(self.config.get("timeoutMs", 60000)) / 1000
        submit = self._curl_post_once_raw(
            url=f"{base}{submit_path}",
            headers=self._headers(operation=operation, api_key=api_key, resource_id=resource_id, request_id=request_id, sequence=True),
            payload_json=json.dumps({"user": {"uid": uid}, "audio": audio, "request": request}, ensure_ascii=False),
            timeout_sec=timeout,
            marker="__DOUBAO_ASR_SUBMIT_CODE__:",
        )
        submit_status = str(submit.headers.get("x-api-status-code") or "").strip()
        if submit.status_code != 200 or submit_status != "20000000":
            raise ValueError(f"Doubao {operation} submit failed: HTTP {submit.status_code}, status {submit_status or '<missing>'}")
        log_id = str(submit.headers.get("x-tt-logid") or "").strip()
        poll_interval = self._positive_number("asr_poll_interval_seconds", asr_poll_interval_seconds, 5)
        poll_timeout = self._positive_number("asr_poll_timeout_seconds", asr_poll_timeout_seconds, 3600)
        started = time.monotonic()
        while True:
            query = self._curl_post_once_raw(
                url=f"{base}{query_path}",
                headers=self._headers(
                    operation=operation,
                    api_key=api_key,
                    resource_id=resource_id,
                    request_id=request_id,
                    sequence=False,
                    log_id=log_id if operation == "asr_idle" else "",
                ),
                payload_json="{}",
                timeout_sec=timeout,
                marker="__DOUBAO_ASR_QUERY_CODE__:",
            )
            status = str(query.headers.get("x-api-status-code") or "").strip()
            if query.status_code != 200:
                raise ValueError(f"Doubao {operation} query returned HTTP {query.status_code}.")
            if status == "20000000":
                try:
                    body = json.loads(query.body)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Doubao {operation} returned invalid JSON.") from exc
                result = body.get("result") if isinstance(body, dict) else None
                if not isinstance(result, dict):
                    raise ValueError(f"Doubao {operation} response is missing result.")
                return {
                    "response": str(result.get("text") or "").strip(),
                    "transcription": result,
                    "audio_info": body.get("audio_info") if isinstance(body.get("audio_info"), dict) else None,
                    "request_id": request_id,
                    "provider_status": status,
                }
            if status not in _PENDING_CODES:
                message = str(query.headers.get("x-api-message") or "").strip()
                raise ValueError(f"Doubao {operation} query failed with status {status or '<missing>'}: {message}")
            if time.monotonic() - started >= poll_timeout:
                raise TimeoutError(f"Doubao {operation} timed out after {poll_timeout:g}s. request_id={request_id}")
            sleep_with_cancel(poll_interval, self._cancel_source())
