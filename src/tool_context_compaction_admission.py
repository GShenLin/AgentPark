from __future__ import annotations

import json

from src.tool_turn_admission import ToolTurnAdmissionDecision
from src.tool_turn_admission import ToolTurnCall
from src.tool_turn_admission import admit_tool_turn


class ToolContextCompactionAdmissionMixin:
    def _admit_tool_context_compaction_turn(
        self,
        calls: list[ToolTurnCall],
    ) -> ToolTurnAdmissionDecision:
        decision = admit_tool_turn(
            calls,
            compaction_gate_active=self._tool_context_compaction_gate_active_now(),
        )
        if decision.rejected_calls:
            self._record_tool_context_compaction_rejected_calls(decision)
            self._emit_tool_context_compaction_admission_notice(decision)
        return decision

    def _record_tool_context_compaction_rejected_calls(
        self,
        decision: ToolTurnAdmissionDecision,
    ) -> None:
        if not self._tool_context_compaction_gate_active_now():
            return
        recorded = getattr(self, "_tool_context_compaction_rejected_call_ids", set())
        rejected_call_ids = set(recorded) if isinstance(recorded, (set, list, tuple)) else set()
        rejected_call_ids.update(
            str(item.call_id).strip()
            for item in decision.rejected_calls
            if str(item.call_id).strip()
        )
        self._tool_context_compaction_rejected_call_ids = rejected_call_ids

    def _emit_tool_context_compaction_admission_notice(
        self,
        decision: ToolTurnAdmissionDecision,
    ) -> None:
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if not callable(emitter):
            return
        emitter(
            message=json.dumps(
                {
                    "admitted_call_ids": [item.call_id for item in decision.admitted_calls],
                    "policy": "tool_context_compaction_checkpoint",
                    "provider_continuation_safe": decision.provider_continuation_safe,
                    "rejected_calls": [
                        {
                            "call_id": item.call_id,
                            "name": item.name,
                            "reason": item.reason,
                        }
                        for item in decision.rejected_calls
                    ],
                    "retry_required": decision.retry_required,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            stage="tool_context_compaction_turn_admission",
        )


__all__ = ["ToolContextCompactionAdmissionMixin"]
