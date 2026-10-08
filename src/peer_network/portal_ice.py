"""Signed, ordered browser ICE updates bound to one admitted Board session."""
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from .contracts import Contract, Signal


class PortalIceCandidate(Contract):
    kind: Literal["ice_candidate"]
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    target: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_key: str = Field(min_length=40, max_length=60)
    expires_at: int
    signature: str = Field(min_length=80, max_length=100)
    sequence: int = Field(ge=0, le=128)
    candidate: str | None = Field(max_length=4096)
    sdp_mid: str | None = Field(max_length=128)
    sdp_mline_index: int | None = Field(ge=0, le=32)

    @model_validator(mode="after")
    def validate_candidate(self):
        if self.candidate is None:
            if self.sdp_mid is not None or self.sdp_mline_index is not None:
                raise ValueError("End of ICE candidates must not name a media section.")
        elif (not self.candidate.startswith("candidate:") or "\n" in self.candidate
              or "\r" in self.candidate or self.sequence == 128
              or (self.sdp_mid is None and self.sdp_mline_index is None)):
            raise ValueError("Invalid browser ICE candidate.")
        return self


PORTAL_SIGNAL = TypeAdapter(Annotated[Signal | PortalIceCandidate, Field(discriminator="kind")])


class PortalIceOrder:
    """Reject out-of-session, duplicate, reordered and post-completion updates."""
    def __init__(self):
        self.binding: tuple[str, str] | None = None
        self.sequence = 0
        self.complete = False

    def accept(self, signal: Signal | PortalIceCandidate):
        if isinstance(signal, Signal):
            if signal.kind != "offer" or self.binding is not None:
                raise ValueError("A Board connection accepts exactly one signed offer.")
            self.binding = (signal.target, signal.session_id)
        else:
            if self.binding != (signal.target, signal.session_id):
                raise ValueError("ICE candidate does not match the Board session.")
            if self.complete or signal.sequence != self.sequence:
                raise ValueError("Replayed or out-of-order Board ICE candidate.")
            self.sequence += 1
            self.complete = signal.candidate is None


async def apply_candidate(pc, signal: PortalIceCandidate):
    from aiortc.sdp import candidate_from_sdp
    if signal.candidate is None:
        await pc.addIceCandidate(None)
        return
    try:
        candidate = candidate_from_sdp(signal.candidate.removeprefix("candidate:"))
    except (ValueError, IndexError, AssertionError) as exc:
        raise ValueError("Malformed browser ICE candidate.") from exc
    candidate.sdpMid = signal.sdp_mid
    candidate.sdpMLineIndex = signal.sdp_mline_index
    await pc.addIceCandidate(candidate)
