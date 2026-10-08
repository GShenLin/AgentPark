"""Completed call transcript contract and its standalone conversation record."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .shared import now_text


class VoiceTranscriptLine(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=128_000)
    offset_ms: int = Field(ge=0)
    incomplete: bool


class VoiceFinish(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["ended", "error"]
    duration_ms: int = Field(ge=0)
    lines: list[VoiceTranscriptLine]


class VoiceCallRecord(VoiceFinish):
    kind: Literal["voice_call"]
    session_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    ended_at: str = Field(min_length=1)
    history_owner: Literal["voice", "node"] = "voice"


def build_voice_record(session_id: str, started_at: str, payload: VoiceFinish, *, ended_at: str | None = None,
                       history_owner: Literal["voice", "node"] = "voice") -> dict:
    ended_at = ended_at if ended_at is not None else now_text()
    return {
        "id": f"voice-{session_id}", "role": "voice", "created_at": ended_at,
        "parts": [{"type": "structured", "data": {
            "kind": "voice_call", "session_id": session_id,
            "started_at": started_at, "ended_at": ended_at,
            "history_owner": history_owner,
            **payload.model_dump(),
        }}],
    }
