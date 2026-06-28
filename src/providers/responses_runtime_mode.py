from __future__ import annotations

from typing import Any

from src.providers.responses_runtime_protocol import ResponsesRuntimeModeDecision


def resolve_responses_runtime_mode(runtime: Any) -> ResponsesRuntimeModeDecision:
    supports = getattr(runtime, "_supports_responses_api", None)
    if callable(supports) and supports():
        return ResponsesRuntimeModeDecision(requested_mode="responses_api", mode="item_level")
    raise ValueError(
        "Responses runtime requires provider.responsesApi=true. "
        "Select a provider that declares Responses API support."
    )


__all__ = ["resolve_responses_runtime_mode"]
