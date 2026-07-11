from __future__ import annotations

from typing import Any


def record_static_contract_limits(result: dict[str, Any], provider_type: str, *, skip_access: bool) -> None:
    if not skip_access:
        return
    if provider_type not in {"openai", "deepseek", "claude", "doubao", "zhipu", "gemini", "hyper3d"}:
        return
    result.setdefault("features", {})
    result.setdefault("unsupported", {})
    for feature in ("responses_api", "web_search", "thinking", "reasoning_effort"):
        if feature not in result["unsupported"]:
            result["unsupported"][feature] = "not tested because provider is not accessible"
