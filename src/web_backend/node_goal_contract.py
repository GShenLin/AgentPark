from __future__ import annotations

import json
from typing import Any

from src.message_protocol import envelope_text


ACTIVE_GOAL_STATUS = "active"
COMPLETE_GOAL_STATUS = "complete"
BLOCKED_GOAL_STATUS = "blocked"
TERMINAL_GOAL_STATUSES = {COMPLETE_GOAL_STATUS, BLOCKED_GOAL_STATUS}
GOAL_COMPLETION_AUDIT_INSTRUCTIONS = (
    "Completion contract:\n"
    '- Keep the original goal scope intact; do not redefine success around the work already done.\n'
    '- Treat completion as unproven until the current state proves the full goal is satisfied.\n'
    '- If the full goal is not proven complete, keep making concrete progress and do not claim completion.\n'
    '- Only when the full goal is proven complete, include a "Goal completion audit:" section with this exact '
    "structured contract:\n"
    "  Original goal: <the full original goal>\n"
    "  Current-state evidence: <evidence from the current project/runtime state>\n"
    "  Verification evidence: <commands, logs, files, or direct checks that prove the evidence>\n"
    "  Known caveats: none\n"
    "  Remaining required work: none\n"
    "- If any caveat, timeout, failed verification, unchecked boundary, or remaining required work exists, do not "
    "use Known caveats: none or Remaining required work: none; keep the goal active instead."
)


class GoalEvaluationError(RuntimeError):
    pass


def has_structured_completion_audit(message: object) -> bool:
    text = envelope_text(message)
    marker = "Goal completion audit:"
    marker_index = text.find(marker)
    if marker_index < 0:
        return False
    audit = text[marker_index + len(marker) :]
    required_labels = (
        "Original goal:",
        "Current-state evidence:",
        "Verification evidence:",
        "Known caveats:",
        "Remaining required work:",
    )
    if any(label not in audit for label in required_labels):
        return False
    return "Known caveats: none" in audit and "Remaining required work: none" in audit


def parse_goal_evaluation(response: object) -> dict[str, str]:
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
    parsed = _parse_json_object(str(text or ""))
    if set(parsed) != {"new_goal_state", "reason"}:
        raise GoalEvaluationError(
            'goal evaluator JSON must contain exactly "new_goal_state" and "reason"'
        )
    status = str(parsed.get("new_goal_state") or "").strip().lower()
    reason = str(parsed.get("reason") or "").strip()
    if status not in {ACTIVE_GOAL_STATUS, COMPLETE_GOAL_STATUS, BLOCKED_GOAL_STATUS}:
        raise GoalEvaluationError(f"invalid new_goal_state: {status!r}")
    if not reason:
        raise GoalEvaluationError("goal evaluation reason is required")
    return {"new_goal_state": status, "reason": reason}


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise GoalEvaluationError("goal evaluator did not return a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise GoalEvaluationError("goal evaluator JSON must be an object")
    return parsed
