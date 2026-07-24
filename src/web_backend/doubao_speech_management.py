"""Provider-side Doubao speech management API boundary."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

from fastapi import HTTPException

from src.audio_speaker_catalog import AudioSpeakerCatalog
from src.config_loader import ConfigLoader
from src.providers.doubao_speech_auth import require_doubao_x_api_key
from src.providers.volcengine_openapi import VolcengineOpenApi

from .domain_base import DomainBase


_SPEECH_ACTIONS = {
    "clone_voice": "/api/v3/tts/voice_clone",
    "get_voice": "/api/v3/tts/get_voice",
    "upgrade_voice": "/api/v3/tts/upgrade_voice",
    "design_voice": "/api/v3/tts/voice_design",
}
_SIGNED_ACTIONS = {
    "list_speakers": ("ListSpeakers", "2025-05-20"),
    "list_voices": ("BatchListMegaTTSTrainStatus", "2023-11-07"),
    "list_hotwords": ("ListBoostingTable", "2022-08-30"),
    "get_hotword": ("GetBoostingTable", "2022-08-30"),
    "delete_hotword": ("DeleteBoostingTable", "2022-08-30"),
    "list_correct_tables": ("ListCorrectTable", "2023-10-30"),
    "get_correct_table": ("GetCorrectTable", "2023-10-30"),
    "delete_correct_table": ("DeleteCorrectTable", "2023-10-30"),
}


class DoubaoSpeechManagementDomain(DomainBase):
    def execute(self, provider_id: str, payload: dict | None = None):
        operation = str((payload or {}).get("operation") or "").strip()
        values = (payload or {}).get("payload")
        if not operation or not isinstance(values, dict):
            raise HTTPException(status_code=400, detail="operation and object payload are required")
        safe_provider_id = str(provider_id or "").strip()
        try:
            config = ConfigLoader().get_provider_config(safe_provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if str(config.get("type") or "").strip().lower() != "doubao":
            raise HTTPException(status_code=400, detail="Doubao speech management requires a doubao provider")
        try:
            if operation in _SPEECH_ACTIONS:
                result = self._speech_request(config, operation, values)
            elif operation in _SIGNED_ACTIONS:
                result = self._signed_request(config, operation, values)
            else:
                raise ValueError(f"Unsupported Doubao speech management operation: {operation}")
            speaker_options = self._speaker_options(operation, result)
            indexed_count = 0
            if operation == "list_speakers":
                indexed_count = AudioSpeakerCatalog().replace_provider_index(
                    safe_provider_id,
                    values["ResourceIDs"],
                    speaker_options,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "operation": operation,
            "result": result,
            "speaker_option_count": indexed_count,
        }

    def _speech_request(self, config: dict, operation: str, payload: dict) -> dict:
        self._validate_speech_payload(operation, payload)
        api_key = require_doubao_x_api_key(config, operation)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        configured_url = str(config.get("baseUrl") or "https://openspeech.bytedance.com").strip()
        parsed_url = urlsplit(configured_url)
        base = (
            f"{parsed_url.scheme}://{parsed_url.netloc}"
            if parsed_url.scheme in {"http", "https"} and parsed_url.netloc
            else configured_url.rstrip("/")
        )
        request = urllib.request.Request(
            base + _SPEECH_ACTIONS[operation],
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": api_key,
                "X-Api-Request-Id": str(uuid.uuid4()),
            },
        )
        timeout = max(1.0, float(config.get("timeoutMs", 60000)) / 1000)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except urllib.error.URLError as exc:
            raise ValueError(f"Doubao {operation} request failed: {exc.reason}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Doubao {operation} returned invalid JSON (HTTP {status}).") from exc
        if not isinstance(result, dict):
            raise ValueError(f"Doubao {operation} response must be a JSON object.")
        code = result.get("code")
        if not 200 <= status < 300 or (code not in {None, 0, 20000000}):
            raise ValueError(f"Doubao {operation} failed (HTTP {status}, code {code}): {result.get('message') or ''}")
        return result

    def _signed_request(self, config: dict, operation: str, payload: dict) -> dict:
        values = dict(payload)
        if operation != "list_speakers":
            values.setdefault("AppID", self._app_id(config))
        self._validate_signed_payload(operation, values)
        client = VolcengineOpenApi(
            access_key_id=str(config.get("speechAccessKeyId") or ""),
            secret_access_key=str(config.get("speechSecretAccessKey") or ""),
            region=str(config.get("speechRegion") or "cn-north-1"),
            service=str(config.get("speechService") or "speech_saas_prod"),
            timeout=max(1.0, float(config.get("timeoutMs", 60000)) / 1000),
        )
        action, version = _SIGNED_ACTIONS[operation]
        if operation == "list_speakers":
            return self._list_all_speakers(client, action, version, values)
        return client.post_json(action, version, values)

    @staticmethod
    def _list_all_speakers(
        client: VolcengineOpenApi,
        action: str,
        version: str,
        payload: dict,
    ) -> dict:
        request_payload = {key: value for key, value in payload.items() if key not in {"Page", "Limit"}}
        page_limit = payload.get("Limit", 30)
        if isinstance(page_limit, bool) or not isinstance(page_limit, int) or page_limit <= 0:
            raise ValueError("list_speakers Limit must be a positive integer.")

        first_result = client.post_json(action, version, {**request_payload, "Page": 1, "Limit": page_limit})
        first_metadata = first_result.get("Result")
        if not isinstance(first_metadata, dict):
            raise ValueError("ListSpeakers response requires an object Result.")
        first_speakers = first_metadata.get("Speakers")
        total = first_metadata.get("Total")
        if not isinstance(first_speakers, list) or isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("ListSpeakers response requires Speakers and a non-negative integer Total.")

        speakers = list(first_speakers)
        page_count = (total + page_limit - 1) // page_limit
        for page in range(2, page_count + 1):
            page_result = client.post_json(
                action,
                version,
                {**request_payload, "Page": page, "Limit": page_limit},
            )
            page_metadata = page_result.get("Result")
            page_speakers = page_metadata.get("Speakers") if isinstance(page_metadata, dict) else None
            if not isinstance(page_speakers, list):
                raise ValueError(f"ListSpeakers page {page} response requires a Speakers list.")
            speakers.extend(page_speakers)

        if len(speakers) != total:
            raise ValueError(f"ListSpeakers returned {len(speakers)} speakers but declared Total={total}.")
        result = dict(first_result)
        result["Result"] = {**first_metadata, "Speakers": speakers, "Total": total}
        return result

    @staticmethod
    def _app_id(config: dict) -> int:
        value = str(config.get("speechAppId") or "").strip()
        if not value.isdigit():
            raise ValueError("This management operation requires a numeric provider speechAppId.")
        return int(value)

    @staticmethod
    def _validate_speech_payload(operation: str, payload: dict) -> None:
        speaker_id = str(payload.get("speaker_id") or "").strip()
        if not speaker_id:
            raise ValueError(f"{operation} requires speaker_id.")
        if operation == "clone_voice":
            audio = payload.get("audio")
            if not isinstance(audio, dict) or not str(audio.get("data") or "").strip():
                raise ValueError("clone_voice requires audio.data base64 content.")
        if operation == "design_voice":
            if not str(payload.get("text") or "").strip() or not isinstance(payload.get("prompt"), dict):
                raise ValueError("design_voice requires text and a prompt object.")

    @staticmethod
    def _validate_signed_payload(operation: str, payload: dict) -> None:
        if operation == "list_speakers":
            resources = payload.get("ResourceIDs")
            if not isinstance(resources, list) or not resources:
                raise ValueError("list_speakers requires non-empty ResourceIDs.")
        if operation in {"get_hotword", "delete_hotword"} and not str(payload.get("BoostingTableID") or "").strip():
            raise ValueError(f"{operation} requires BoostingTableID.")
        if operation in {"get_correct_table", "delete_correct_table"} and not str(payload.get("TableID") or "").strip():
            raise ValueError(f"{operation} requires TableID.")

    @staticmethod
    def _speaker_options(operation: str, result: dict) -> list[dict[str, str]]:
        metadata = result.get("Result") if isinstance(result.get("Result"), dict) else {}
        output: list[dict[str, str]] = []
        if operation == "list_speakers":
            items = metadata.get("Speakers") if isinstance(metadata.get("Speakers"), list) else []
            for item in items:
                if isinstance(item, dict) and str(item.get("VoiceType") or "").strip():
                    output.append({
                        "value": str(item["VoiceType"]).strip(),
                        "label": str(item.get("Name") or item["VoiceType"]).strip(),
                    })
        elif operation == "list_voices":
            items = metadata.get("Statuses") if isinstance(metadata.get("Statuses"), list) else []
            for item in items:
                if isinstance(item, dict) and str(item.get("SpeakerID") or "").strip():
                    output.append({
                        "value": str(item["SpeakerID"]).strip(),
                        "label": str(item.get("Alias") or item["SpeakerID"]).strip(),
                    })
        return output


__all__ = ["DoubaoSpeechManagementDomain"]
