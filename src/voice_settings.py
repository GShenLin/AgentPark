"""Node-owned voice selection. Vendors validate their own model/voice catalogs."""
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator


RealtimeVoice = Literal["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
VOICE_MODEL = "gpt-realtime-2.1"


class VoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider_id: str = ""
    model: str = Field(default=VOICE_MODEL, min_length=1, max_length=200)
    voice: str = Field(default="marin", min_length=1, max_length=200)

    @field_validator("provider_id", "model", "voice")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("语音 Provider 和模型标识不能包含首尾空白。")
        return value


NODE_VOICE_FIELDS = {"voice_provider_id": "provider_id", "voice_model": "model", "voice": "voice"}
NODE_VOICE_DEFAULTS = {
    key: VoiceSettings().model_dump()[field] for key, field in NODE_VOICE_FIELDS.items()
}


def node_voice_settings(config: dict) -> VoiceSettings:
    return VoiceSettings.model_validate({
        field: config[key] for key, field in NODE_VOICE_FIELDS.items() if key in config
    })


def supports_openai_voice(config: dict) -> bool:
    return config.get("type") == "openai" and config.get("authMode") in {"codex", "oauth"}


def voice_catalog() -> list[dict[str, str]]:
    return [{"id": voice, "label": voice.title()} for voice in get_args(RealtimeVoice)]
