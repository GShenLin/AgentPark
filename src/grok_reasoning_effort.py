from __future__ import annotations


GROK_REASONING_EFFORT_VALUES_BY_MODEL = {
    "grok-4.5": ("low", "medium", "high"),
}


def require_grok_reasoning_effort(model: object, value: object) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError(_error_message(model))
    effort = value.strip().lower()
    if not effort:
        return ""
    model_name = str(model or "").strip().lower()
    supported_values = GROK_REASONING_EFFORT_VALUES_BY_MODEL.get(model_name)
    if supported_values is None:
        raise ValueError(f"Grok reasoning_effort is not defined for model '{model_name or '<empty>'}'.")
    if effort not in supported_values:
        raise ValueError(_error_message(model))
    return effort


def grok_reasoning_effort_values(model: object) -> list[str]:
    model_name = str(model or "").strip().lower()
    return list(GROK_REASONING_EFFORT_VALUES_BY_MODEL.get(model_name, ()))


def _error_message(model: object) -> str:
    model_name = str(model or "").strip() or "configured model"
    if model_name.lower() == "grok-4.5":
        return "Grok 4.5 reasoning_effort must be low, medium, or high."
    return f"Grok reasoning_effort is invalid for model '{model_name}'."
