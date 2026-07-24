from __future__ import annotations

import json
import os

from src.config_loader import ConfigLoader
from src.file_transaction import atomic_write_text, run_with_interprocess_lock


class AudioSpeakerCatalog:
    VERSION = 1
    FILENAME = "audio_speaker.json"

    def __init__(self, path: str | None = None) -> None:
        self.path = os.path.abspath(path or self._default_path())

    @staticmethod
    def _default_path() -> str:
        provider_path = ConfigLoader().get_provider_config_path()
        return os.path.join(os.path.dirname(provider_path), AudioSpeakerCatalog.FILENAME)

    def get_provider_options(self, provider_id: str) -> list[dict[str, str]]:
        safe_provider_id = self._provider_id(provider_id)
        document = self._read_document()
        provider_index = document["providers"].get(safe_provider_id)
        if provider_index is None:
            return []
        if not isinstance(provider_index, dict):
            raise ValueError(f"audio_speaker.json provider '{safe_provider_id}' must be an object.")
        speakers = provider_index.get("speakers")
        if not isinstance(speakers, dict):
            raise ValueError(f"audio_speaker.json provider '{safe_provider_id}' requires a speakers object.")

        options: list[dict[str, str]] = []
        for voice_type, label in speakers.items():
            safe_voice_type = str(voice_type or "").strip()
            if not safe_voice_type or not isinstance(label, str) or not label.strip():
                raise ValueError(
                    f"audio_speaker.json provider '{safe_provider_id}' contains an invalid speaker index entry."
                )
            options.append({"value": safe_voice_type, "label": label.strip()})
        return options

    def replace_provider_index(
        self,
        provider_id: str,
        resource_ids: list[object],
        options: list[dict[str, str]],
    ) -> int:
        safe_provider_id = self._provider_id(provider_id)
        normalized_resources = self._resource_ids(resource_ids)
        speakers = self._speaker_index(options)

        def write() -> int:
            document = self._read_document()
            providers = dict(document["providers"])
            providers[safe_provider_id] = {
                "resource_ids": normalized_resources,
                "speakers": speakers,
            }
            output = {
                "version": self.VERSION,
                "providers": providers,
            }
            atomic_write_text(
                self.path,
                json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return len(speakers)

        return run_with_interprocess_lock(self.path + ".lock", write)

    def _read_document(self) -> dict:
        if not os.path.isfile(self.path):
            return {"version": self.VERSION, "providers": {}}
        with open(self.path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        if not isinstance(document, dict):
            raise ValueError("audio_speaker.json must contain a top-level object.")
        if document.get("version") != self.VERSION:
            raise ValueError(f"audio_speaker.json version must be {self.VERSION}.")
        if not isinstance(document.get("providers"), dict):
            raise ValueError("audio_speaker.json field 'providers' must be an object.")
        return document

    @staticmethod
    def _provider_id(provider_id: str) -> str:
        value = str(provider_id or "").strip()
        if not value:
            raise ValueError("audio speaker provider_id is required.")
        return value

    @staticmethod
    def _resource_ids(resource_ids: list[object]) -> list[str]:
        if not isinstance(resource_ids, list):
            raise ValueError("audio speaker resource_ids must be an array.")
        output: list[str] = []
        seen: set[str] = set()
        for item in resource_ids:
            value = str(item or "").strip()
            if not value:
                raise ValueError("audio speaker resource_ids must contain non-empty strings.")
            if value not in seen:
                seen.add(value)
                output.append(value)
        if not output:
            raise ValueError("audio speaker resource_ids must not be empty.")
        return output

    @staticmethod
    def _speaker_index(options: list[dict[str, str]]) -> dict[str, str]:
        if not isinstance(options, list):
            raise ValueError("audio speaker options must be an array.")
        speakers: dict[str, str] = {}
        for item in options:
            if not isinstance(item, dict):
                raise ValueError("audio speaker options must contain objects.")
            voice_type = str(item.get("value") or "").strip()
            label = str(item.get("label") or voice_type).strip()
            if not voice_type or not label:
                raise ValueError("audio speaker options require non-empty value and label fields.")
            if voice_type in speakers:
                raise ValueError(f"audio speaker options contain duplicate VoiceType '{voice_type}'.")
            speakers[voice_type] = label
        return speakers


__all__ = ["AudioSpeakerCatalog"]
