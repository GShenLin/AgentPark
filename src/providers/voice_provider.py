"""Realtime voice contract: catalogs, validation, and owned call resources."""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.voice_settings import VoiceSettings
from .voice_control import VoiceControl

VoiceProtocol = Literal["openai-realtime-v1", "agentpark-voice-v4", "volcengine-rtc-v1"]
VoiceDelivery = Literal["accepted", "duplicate"]


class VoiceTaskUpdate(BaseModel):
    """Authoritative task lifecycle snapshot read from the original node."""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    text: str = Field(max_length=128_000)
    task_id: str = Field(min_length=1, max_length=200)



@dataclass(frozen=True)
class VoiceOption:
    id: str
    label: str


@dataclass(frozen=True)
class VoiceModel:
    id: str
    label: str
    voices: tuple[VoiceOption, ...]


class VoiceSession(ABC):
    async def control(self, command: VoiceControl) -> None:
        raise ValueError("此语音供应商不支持 RTC 控制。")

    @abstractmethod
    async def deliver_update(self, delegation_id: str, result: VoiceTaskUpdate) -> VoiceDelivery:
        """Publish accepted, progress, or terminal state through the provider protocol."""

    @abstractmethod
    def close(self) -> None:
        """Request idempotent teardown, including from an HTTP worker thread."""

    @abstractmethod
    async def aclose(self) -> None:
        """Wait for all owned media and network resources to close."""


@dataclass(frozen=True)
class VoiceCall:
    sdp: str
    model: str
    protocol: VoiceProtocol
    session: VoiceSession | None = None

    def connection(self) -> dict:
        return {"transport": "webrtc", "sdp": self.sdp}


@dataclass(frozen=True)
class RtcVoiceCall:
    app_id: str
    room_id: str
    user_id: str
    bot_id: str
    token: str
    model: str
    session: VoiceSession
    protocol: VoiceProtocol = "volcengine-rtc-v1"

    def connection(self) -> dict:
        return {"transport": "volcengine-rtc", "app_id": self.app_id,
                "room_id": self.room_id, "user_id": self.user_id,
                "bot_id": self.bot_id, "token": self.token}


class VoiceProvider(ABC):
    id: str
    label: str
    protocol: VoiceProtocol
    delegation: bool = False
    server_media: bool = False
    node_owned_dialogue: bool = False
    models: tuple[VoiceModel, ...]
    transport: Literal["webrtc", "volcengine-rtc"] = "webrtc"

    @classmethod
    @abstractmethod
    def accepts(cls, config: dict) -> bool: ...

    @classmethod
    def catalog(cls) -> dict:
        return {"id": cls.id, "label": cls.label, "delegation": cls.delegation,
                "node_owned_dialogue": cls.node_owned_dialogue,
                "models": [asdict(model) for model in cls.models]}

    @classmethod
    def validate(cls, settings: VoiceSettings) -> None:
        model = next((item for item in cls.models if item.id == settings.model), None)
        if model is None:
            raise ValueError(f"{cls.label} 不支持语音模型 {settings.model}，请重新选择语音模型。")
        if settings.voice not in {item.id for item in model.voices}:
            raise ValueError(f"语音模型 {settings.model} 不支持音色 {settings.voice}，请重新选择音色。")

    @abstractmethod
    async def create_call(self, config: dict, sdp: str | None, context: str, settings: VoiceSettings,
                          *, ice_servers: tuple[dict, ...] = ()) -> VoiceCall | RtcVoiceCall: ...
