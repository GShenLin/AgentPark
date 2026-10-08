"""Strict RTC control commands, separate from provider-native tool results."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class RtcAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["activate", "heartbeat"]


class RtcScreen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["screen"]
    enabled: bool
    fps: int = Field(ge=1, le=30)


VoiceControl = Annotated[RtcAction | RtcScreen, Field(discriminator="action")]
