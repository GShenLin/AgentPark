from __future__ import annotations

from typing import Any


KIMI_WEB_SEARCH_TOOL_NAME = "$web_search"


def kimi_model_family(model: object) -> str:
    normalized = str(model or "").strip().lower()
    if normalized.startswith("kimi-k3"):
        return "k3"
    if normalized.startswith("kimi-k2.7-code"):
        return "k2.7-code"
    if normalized.startswith("kimi-k2.6"):
        return "k2.6"
    if normalized.startswith("kimi-k2.5"):
        return "k2.5"
    return ""


def build_kimi_reasoning_fields(
    *,
    model: object,
    thinking_mode: object,
    reasoning_effort: object,
    web_search_enabled: bool,
) -> dict[str, Any]:
    model_name = str(model or "").strip()
    family = kimi_model_family(model_name)
    if not family:
        raise ValueError(f"Unsupported Kimi model contract: {model_name or '<empty>'}.")

    thinking = str(thinking_mode or "disabled").strip().lower() or "disabled"
    effort = str(reasoning_effort or "").strip().lower()

    if family == "k3":
        if thinking not in {"disabled"}:
            raise ValueError("Kimi K3 does not accept the K2.x thinking parameter; set thinking=disabled.")
        if effort and effort != "max":
            raise ValueError("Kimi K3 reasoning_effort currently supports only 'max'.")
        return {"reasoning_effort": "max"} if effort == "max" else {}

    if effort:
        raise ValueError(f"Kimi {family} does not support reasoning_effort.")

    if family == "k2.7-code":
        if web_search_enabled:
            raise ValueError("Kimi K2.7 Code cannot use $web_search because its thinking mode cannot be disabled.")
        if thinking == "disabled":
            raise ValueError("Kimi K2.7 Code thinking cannot be disabled.")
        if thinking not in {"enabled", "auto"}:
            raise ValueError("Kimi K2.7 Code thinking must be enabled.")
        return {"thinking": {"type": "enabled", "keep": "all"}}

    if thinking not in {"enabled", "disabled"}:
        raise ValueError(f"Kimi {family} thinking must be 'enabled' or 'disabled'.")
    if web_search_enabled and thinking != "disabled":
        raise ValueError(f"Kimi {family} $web_search requires thinking=disabled.")
    return {"thinking": {"type": thinking}}


def build_kimi_web_search_tool() -> dict[str, Any]:
    return {
        "type": "builtin_function",
        "function": {"name": KIMI_WEB_SEARCH_TOOL_NAME},
    }


def has_kimi_web_search_tool(tools: object) -> bool:
    for item in tools if isinstance(tools, list) else []:
        if not isinstance(item, dict) or str(item.get("type") or "").strip() != "builtin_function":
            continue
        function = item.get("function")
        if isinstance(function, dict) and str(function.get("name") or "").strip() == KIMI_WEB_SEARCH_TOOL_NAME:
            return True
    return False


__all__ = [
    "KIMI_WEB_SEARCH_TOOL_NAME",
    "build_kimi_reasoning_fields",
    "build_kimi_web_search_tool",
    "has_kimi_web_search_tool",
    "kimi_model_family",
]
