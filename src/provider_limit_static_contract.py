from __future__ import annotations

from typing import Any


def record_static_contract_limits(result: dict[str, Any], provider_type: str, *, skip_access: bool) -> None:
    if not skip_access:
        return
    if provider_type not in {"openai", "deepseek", "kimi", "claude", "doubao", "grok", "zhipu", "gemini", "hyper3d"}:
        return
    result.setdefault("features", {})
    result.setdefault("inconclusive", {})
    for feature in ("responses_api", "web_search", "thinking", "reasoning_effort"):
        result["features"].setdefault(
            feature,
            {
                "supported": False,
                "outcome": "not_tested",
                "reason": "not tested because provider is not accessible",
            },
        )
        result["inconclusive"].setdefault(feature, "not tested because provider is not accessible")
