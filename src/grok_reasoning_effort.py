from __future__ import annotations


GROK_REASONING_EFFORT_VALUES = ("low", "medium", "high", "xhigh")


def normalize_grok_reasoning_effort(value: object) -> str:
    """Translate AgentPark's provider-neutral value at the Grok boundary."""
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("Grok reasoning_effort must be a string.")
    effort = value.strip().lower()
    # `none` is part of AgentPark's common agent configuration. At the Grok
    # provider boundary it means no explicit effort field is sent.
    if effort in {"", "none"}:
        return ""
    return effort


def require_grok_reasoning_effort(value: object) -> str:
    effort = normalize_grok_reasoning_effort(value)
    if not effort:
        return ""
    if effort not in GROK_REASONING_EFFORT_VALUES:
        allowed = ", ".join(GROK_REASONING_EFFORT_VALUES)
        raise ValueError(f"Grok reasoning_effort must be one of: {allowed}.")
    return effort


def grok_reasoning_effort_values() -> list[str]:
    return list(GROK_REASONING_EFFORT_VALUES)
