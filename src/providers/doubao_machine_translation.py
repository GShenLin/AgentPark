"""Doubao section 6.1 machine translation runtime."""
from __future__ import annotations

import json
import uuid

from src.service_host import HostBoundService
from src.providers.doubao_speech_auth import require_doubao_x_api_key


_ENDPOINT = "/api/v3/machine_translation/matx_translate"


class DoubaoMachineTranslation(HostBoundService):
    @staticmethod
    def _input_text(messages: object) -> str:
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
    def _json_value(name: str, value: object, expected_type: type, default: object):
        if value in (None, ""):
            return default
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, expected_type):
            raise ValueError(f"{name} must be a JSON {expected_type.__name__}.")
        return parsed

    def translate_text(
        self,
        messages: object,
        *,
        translation_source_language: object = "",
        translation_target_language: object = "en",
        translation_text_list: object = "",
        translation_corpus: object = "",
        translation_resource_id: object = "volc.speech.mt",
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        api_key = require_doubao_x_api_key(self.config, "translate")
        target = str(translation_target_language or "").strip()
        if not target:
            raise ValueError("translation_target_language is required.")
        configured_texts = self._json_value("translation_text_list", translation_text_list, list, [])
        if configured_texts:
            if any(not isinstance(item, str) or not item.strip() for item in configured_texts):
                raise ValueError("translation_text_list must contain only non-empty strings.")
            texts = [item.strip() for item in configured_texts]
        else:
            input_text = self._input_text(messages)
            texts = [input_text] if input_text else []
        if not texts:
            raise ValueError("translate requires input text or translation_text_list.")
        if len(texts) > 16:
            raise ValueError("translation_text_list exceeds the documented 16-item limit.")
        payload: dict = {"target_language": target, "text_list": texts}
        source = str(translation_source_language or "").strip()
        if source:
            payload["source_language"] = source
        corpus = self._json_value("translation_corpus", translation_corpus, dict, {})
        if corpus:
            payload["corpus"] = corpus
        resource_id = str(translation_resource_id or "").strip()
        if not resource_id:
            raise ValueError("translation_resource_id is required.")
        request_id = str(uuid.uuid4())
        base = str(self.config.get("speechBaseUrl") or "https://openspeech.bytedance.com").rstrip("/")
        result = self._post_json_with_retry(
            endpoint="machine_translation/matx_translate",
            url=f"{base}{_ENDPOINT}",
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": api_key,
                "X-Api-Resource-Id": resource_id,
                "X-Api-Request-Id": request_id,
            },
            payload_json=json.dumps(payload, ensure_ascii=False),
            max_retries=int(self.config.get("maxRetries", 2)),
            retry_delay=float(self.config.get("retryDelaySec", 1)),
        )
        if not isinstance(result, dict) or result.get("code") != 20000000:
            code = result.get("code") if isinstance(result, dict) else None
            message = result.get("message") if isinstance(result, dict) else "non-object response"
            raise ValueError(f"Doubao translate returned code {code}: {message}")
        data = result.get("data")
        translations = data.get("translation_list") if isinstance(data, dict) else None
        if not isinstance(translations, list) or len(translations) != len(texts):
            raise ValueError("Doubao translate returned an invalid translation_list.")
        output_texts = [str(item.get("translation") or "").strip() for item in translations if isinstance(item, dict)]
        if len(output_texts) != len(texts) or any(not text for text in output_texts):
            raise ValueError("Doubao translate returned an empty or malformed translation.")
        return {
            "response": "\n".join(output_texts),
            "translations": translations,
            "request_id": request_id,
        }
