from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool.tool_call_protocol import ToolCallParseFailure


COMPACTION_TOOL_NAME = "compact_tool_context"
ToolTurnCall = ToolCallEnvelope | ToolCallParseFailure


@dataclass(frozen=True)
class RejectedToolTurnCall:
    call: ToolTurnCall
    reason: Literal["not_offered_during_compaction", "duplicate_compaction_call"]

    @property
    def name(self) -> str:
        return self.call.name

    @property
    def call_id(self) -> str:
        return self.call.call_id


@dataclass(frozen=True)
class ToolTurnAdmissionDecision:
    admitted_calls: tuple[ToolTurnCall, ...]
    rejected_calls: tuple[RejectedToolTurnCall, ...] = ()
    retry_required: bool = False
    provider_continuation_safe: bool = True

    @property
    def canonicalized(self) -> bool:
        return bool(self.rejected_calls)


def admit_tool_turn(
    calls: list[ToolTurnCall],
    *,
    compaction_gate_active: bool,
) -> ToolTurnAdmissionDecision:
    if not isinstance(calls, list) or not all(isinstance(item, (ToolCallEnvelope, ToolCallParseFailure)) for item in calls):
        raise TypeError("admit_tool_turn requires normalized ToolCallEnvelope or ToolCallParseFailure items")
    if not compaction_gate_active:
        return ToolTurnAdmissionDecision(admitted_calls=tuple(calls))

    compaction_calls = [item for item in calls if item.name == COMPACTION_TOOL_NAME]
    if not compaction_calls:
        return ToolTurnAdmissionDecision(
            admitted_calls=(),
            rejected_calls=tuple(
                RejectedToolTurnCall(
                    call=item,
                    reason="not_offered_during_compaction",
                )
                for item in calls
            ),
            retry_required=bool(calls),
            provider_continuation_safe=False,
        )

    admitted = compaction_calls[0]
    rejected: list[RejectedToolTurnCall] = []
    admitted_seen = False
    for item in calls:
        if item is admitted and not admitted_seen:
            admitted_seen = True
            continue
        reason: Literal["not_offered_during_compaction", "duplicate_compaction_call"]
        reason = "duplicate_compaction_call" if item.name == COMPACTION_TOOL_NAME else "not_offered_during_compaction"
        rejected.append(RejectedToolTurnCall(call=item, reason=reason))

    return ToolTurnAdmissionDecision(
        admitted_calls=(admitted,),
        rejected_calls=tuple(rejected),
        retry_required=False,
        provider_continuation_safe=not rejected,
    )


__all__ = [
    "COMPACTION_TOOL_NAME",
    "RejectedToolTurnCall",
    "ToolTurnAdmissionDecision",
    "ToolTurnCall",
    "admit_tool_turn",
]
