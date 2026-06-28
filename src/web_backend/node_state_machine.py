from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NODE_STATES = {"idle", "working", "stop"}


@dataclass(frozen=True)
class NodeRecoveryPlan:
    changed: bool
    reason: str = ""
    after_state: str = "idle"
    requeue_inflight: bool = False
    clear_inflight: bool = False
    preserve_stop: bool = False
    pending_count: int = 0

    def to_result(self) -> dict[str, Any]:
        return {
            "recovered": self.changed,
            "reason": self.reason,
            "after_state": self.after_state,
            "inflight_requeued": self.requeue_inflight,
            "pending_count": self.pending_count,
        }


def parse_node_state(value: object) -> str:
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate == "running":
            return "working"
        if candidate in NODE_STATES:
            return candidate
    return "idle"


def plan_startup_recovery(payload: dict[str, Any]) -> NodeRecoveryPlan:
    before_state = parse_node_state(payload.get("state"))
    pending_count = _pending_count(payload)
    if before_state == "stop":
        return NodeRecoveryPlan(
            changed=False,
            reason="stop_state_preserved",
            after_state="stop",
            preserve_stop=True,
            pending_count=pending_count,
        )

    has_inflight = isinstance(payload.get("inflight"), dict)
    if has_inflight:
        return NodeRecoveryPlan(
            changed=True,
            reason="startup_inflight_requeued",
            after_state="idle",
            requeue_inflight=True,
            clear_inflight=True,
            pending_count=pending_count + 1,
        )

    if before_state == "working" and not _is_clock_waiting(payload):
        return NodeRecoveryPlan(
            changed=True,
            reason="startup_missing_inflight",
            after_state="idle",
            clear_inflight=True,
            pending_count=pending_count,
        )

    return NodeRecoveryPlan(changed=False, after_state=before_state, pending_count=pending_count)


def plan_stale_working_recovery(payload: dict[str, Any]) -> NodeRecoveryPlan:
    before_state = parse_node_state(payload.get("state"))
    pending_count = _pending_count(payload)
    if before_state != "working":
        return NodeRecoveryPlan(changed=False, after_state=before_state, pending_count=pending_count)
    if _is_clock_waiting(payload):
        return NodeRecoveryPlan(changed=False, reason="clock_waiting", after_state="working", pending_count=pending_count)
    if isinstance(payload.get("inflight"), dict):
        return NodeRecoveryPlan(changed=False, reason="active_inflight", after_state="working", pending_count=pending_count)
    return NodeRecoveryPlan(
        changed=True,
        reason="missing_inflight",
        after_state="idle",
        clear_inflight=True,
        pending_count=pending_count,
    )


def apply_recovery_plan(payload: dict[str, Any], plan: NodeRecoveryPlan) -> None:
    if not plan.changed:
        return
    if plan.requeue_inflight and isinstance(payload.get("inflight"), dict):
        pending = payload.get("pending")
        if not isinstance(pending, list):
            pending = []
        pending.insert(0, payload["inflight"])
        payload["pending"] = pending
    pending = payload.get("pending")
    payload["pending_count"] = len(pending) if isinstance(pending, list) else 0
    if plan.clear_inflight:
        payload.pop("inflight", None)
        payload.pop("inflight_at", None)
    payload.pop("_stop_requested", None)
    payload["state"] = plan.after_state


def _pending_count(payload: dict[str, Any]) -> int:
    pending = payload.get("pending")
    if isinstance(pending, list):
        return len(pending)
    value = payload.get("pending_count")
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return 0


def _is_clock_waiting(payload: dict[str, Any]) -> bool:
    return (
        parse_node_state(payload.get("state")) == "working"
        and str(payload.get("type_id") or "").strip() == "clock_node"
        and bool(payload.get("_clock_running"))
        and not isinstance(payload.get("inflight"), dict)
    )
