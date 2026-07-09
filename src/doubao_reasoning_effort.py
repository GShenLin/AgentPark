from __future__ import annotations


DOUBAO_REASONING_EFFORT_VALUES = {"low", "medium", "high"}


def require_doubao_reasoning_effort(value: object) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("Doubao Ark Responses reasoning_effort must be low, medium, or high.")
    effort = value.strip()
    if not effort:
        return ""
    if effort not in DOUBAO_REASONING_EFFORT_VALUES:
        raise ValueError("Doubao Ark Responses reasoning_effort must be low, medium, or high.")
    return effort
