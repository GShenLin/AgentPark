"""Strict RTC control commands, separate from provider-native tool results."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class RtcAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["activate", "heartbeat"]


VoiceControl = RtcAction
