"""Doubao section 2.3 synchronous recording-file ASR (flash edition)."""
from __future__ import annotations

import base64
import json
import os
import uuid
from urllib.parse import urlparse

from src.service_host import HostBoundService
from src.providers.doubao_speech_auth import require_doubao_x_api_key
from src.value_parsing import parse_optional_bool_value


_ENDPOINT = "/api/v3/auc/bigmodel/recognize/flash"
_MAX_AUDIO_BYTES = 100 * 1024 * 1024
_EXTENSIONS = {".wav", ".mp3", ".ogg", ".opus"}


class DoubaoAsrFlash(HostBoundService):
    @staticmethod
    def _message_audio(messages: object) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "reference_resource"
                    and str(part.get("kind") or "").strip().lower() == "audio"
                ):
                    return str(part.get("uri") or "").strip()
        return ""

    @staticmethod
    def _audio_payload(uri: str) -> dict:
        value = str(uri or "").strip()
        if not value:
            raise ValueError("asr_flash requires an audio attachment or asr_source_audio.")
        if value.startswith(("http://", "https://")):
            ext = os.path.splitext(urlparse(value).path)[1].lower()
            if ext and ext not in _EXTENSIONS:
                raise ValueError(f"Unsupported asr_flash audio URL extension: {ext}")
            return {"url": value}
        if value.startswith("asset://"):
            raise ValueError("asset:// ASR input must be exposed as a public URL or uploaded local path.")
        path = value[7:] if value.startswith("file://") else value
        if not os.path.isfile(path):
            raise ValueError(f"ASR audio file does not exist: {path}")
        ext = os.path.splitext(path)[1].lower()
        if ext not in _EXTENSIONS:
            raise ValueError(f"Unsupported asr_flash audio format: {ext or '<none>'}")
        if os.path.getsize(path) > _MAX_AUDIO_BYTES:
            raise ValueError("asr_flash audio exceeds the documented 100 MB limit.")
        with open(path, "rb") as handle:
            return {"data": base64.b64encode(handle.read()).decode("ascii")}

    def recognize_asr_flash(
        self,
        messages: object,
        *,
        asr_source_audio: object = "",
        asr_resource_id: object = "volc.bigasr.auc_turbo",
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
        api_key = require_doubao_x_api_key(self.config, "asr_flash")
        resource_id = str(asr_resource_id or "").strip()
        if not resource_id:
            raise ValueError("asr_resource_id is required.")
        audio_uri = self._message_audio(messages) or str(asr_source_audio or "").strip()
        uid = str(asr_uid or self.config.get("speechAppId") or api_key).strip()
        request_id = str(uuid.uuid4())
        request_options = {
            "model_name": str(asr_model_name or "bigmodel").strip() or "bigmodel",
            "enable_itn": bool(parse_optional_bool_value("asr_enable_itn", asr_enable_itn)),
            "enable_punc": bool(parse_optional_bool_value("asr_enable_punc", asr_enable_punc)),
            "enable_ddc": bool(parse_optional_bool_value("asr_enable_ddc", asr_enable_ddc)),
            "enable_speaker_info": bool(parse_optional_bool_value("asr_enable_speaker_info", asr_enable_speaker_info)),
        }
        payload = {
            "user": {"uid": uid},
            "audio": self._audio_payload(audio_uri),
            "request": request_options,
        }
        base = str(self.config.get("speechBaseUrl") or "https://openspeech.bytedance.com").rstrip("/")
        response = self._curl_post_once_raw(
            url=f"{base}{_ENDPOINT}",
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": api_key,
                "X-Api-Resource-Id": resource_id,
                "X-Api-Request-Id": request_id,
                "X-Api-Sequence": "-1",
            },
            payload_json=json.dumps(payload, ensure_ascii=False),
            timeout_sec=float(self.config.get("timeoutMs", 60000)) / 1000,
            marker="__DOUBAO_ASR_FLASH_CODE__:",
        )
        if response.status_code != 200:
            raise ValueError(f"Doubao asr_flash returned HTTP {response.status_code}: {response.body[-500:]}")
        provider_status = str(response.headers.get("x-api-status-code") or "").strip()
        if provider_status != "20000000":
            message = str(response.headers.get("x-api-message") or "").strip()
            raise ValueError(f"Doubao asr_flash returned status {provider_status or '<missing>'}: {message}")
        try:
            body = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ValueError("Doubao asr_flash returned invalid JSON.") from exc
        if not isinstance(body, dict):
            raise ValueError("Doubao asr_flash response must be a JSON object.")
        result = body.get("result")
        if not isinstance(result, dict):
            raise ValueError("Doubao asr_flash response is missing result.")
        text = str(result.get("text") or "").strip()
        return {
            "response": text,
            "transcription": result,
            "audio_info": body.get("audio_info") if isinstance(body.get("audio_info"), dict) else None,
            "request_id": request_id,
            "provider_status": provider_status,
        }
