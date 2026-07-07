from __future__ import annotations


DOUBAO_REASONING_EFFORT_VALUES = {"low", "medium", "high"}
DOUBAO_REASONING_EFFORT_ALIASES = {"xhigh": "high"}


def normalize_doubao_reasoning_effort(value: object) -> str:
    effort = str(value or "").strip().lower()
    if not effort:
        return ""
    return DOUBAO_REASONING_EFFORT_ALIASES.get(effort, effort)


def require_doubao_reasoning_effort(value: object) -> str:
    effort = normalize_doubao_reasoning_effort(value)
    if not effort:
        return ""
    if effort not in DOUBAO_REASONING_EFFORT_VALUES:
        raise ValueError("Doubao Ark Responses reasoning_effort must be low, medium, or high.")
    return effort
