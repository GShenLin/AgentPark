from __future__ import annotations

from copy import deepcopy
from typing import Any


USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "reasoning_output_tokens",
)


def extract_provider_usage(result: object) -> dict[str, int]:
    if not isinstance(result, dict):
        return {}
    raw = result.get("usage")
    if not isinstance(raw, dict):
        raw = result.get("usageMetadata")
    if not isinstance(raw, dict):
        return {}

    input_tokens = _first_int(raw, "input_tokens", "prompt_tokens", "promptTokenCount")
    output_tokens = _first_int(raw, "output_tokens", "completion_tokens", "candidatesTokenCount")
    total_tokens = _first_int(raw, "total_tokens", "totalTokenCount")
    cached_input_tokens = _first_int(
        raw,
        "cache_read_input_tokens",
        "cached_input_tokens",
        "cachedContentTokenCount",
    )
    cache_write_input_tokens = _first_int(raw, "cache_creation_input_tokens")
    reasoning_output_tokens = _first_int(raw, "thoughtsTokenCount")

    input_details = raw.get("input_tokens_details") or raw.get("prompt_tokens_details")
    if isinstance(input_details, dict):
        details_cached = _first_int(input_details, "cached_tokens")
        if details_cached is not None:
            cached_input_tokens = details_cached
    output_details = raw.get("output_tokens_details") or raw.get("completion_tokens_details")
    if isinstance(output_details, dict):
        details_reasoning = _first_int(output_details, "reasoning_tokens")
        if details_reasoning is not None:
            reasoning_output_tokens = details_reasoning

    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    values = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_input_tokens": cache_write_input_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
    }
    return {key: value for key, value in values.items() if value is not None}


def sanitize_provider_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    usage: dict[str, int] = {}
    for key in USAGE_FIELDS:
        normalized = _non_negative_int(value.get(key))
        if normalized is not None:
            usage[key] = normalized
    return usage


def add_provider_usage_totals(totals: dict[str, Any], usage: object) -> None:
    normalized = sanitize_provider_usage(usage)
    if not normalized:
        return
    totals["completed_request_count"] = (_non_negative_int(totals.get("completed_request_count")) or 0) + 1
    for key, value in normalized.items():
        total_key = f"actual_{key}"
        totals[total_key] = (_non_negative_int(totals.get(total_key)) or 0) + value


class ProviderRequestTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._summaries: list[dict[str, Any]] = []
        self._totals: dict[str, Any] = {
            "request_count": 0,
            "approx_input_chars": 0,
            "approx_input_tokens": 0,
            "tool_call_chars": 0,
            "tool_result_chars": 0,
        }

    def record_summary(self, summary: dict[str, Any]) -> None:
        copied = deepcopy(summary)
        self._summaries.append(copied)
        self._totals["request_count"] += 1
        for summary_key, total_key in (
            ("approx_input_chars", "approx_input_chars"),
            ("approx_input_tokens", "approx_input_tokens"),
            ("tool_call_chars_total", "tool_call_chars"),
            ("tool_result_chars_total", "tool_result_chars"),
        ):
            self._totals[total_key] += _non_negative_int(summary.get(summary_key)) or 0
        request_index = _non_negative_int(summary.get("request_index"))
        if request_index is not None:
            self._totals["last_request_index"] = request_index

    def record_completion(self, request_index: object, usage: object) -> dict[str, Any] | None:
        normalized_index = _non_negative_int(request_index)
        normalized_usage = sanitize_provider_usage(usage)
        if normalized_index is None or not normalized_usage:
            return None
        for summary in reversed(self._summaries):
            if _non_negative_int(summary.get("request_index")) == normalized_index:
                summary["usage"] = dict(normalized_usage)
                break
        add_provider_usage_totals(self._totals, normalized_usage)
        return {"request_index": normalized_index, "usage": normalized_usage}

    def snapshot(self) -> dict[str, Any]:
        if not self._summaries:
            return {}
        return {
            "summaries": deepcopy(self._summaries),
            "totals": deepcopy(self._totals),
        }


def _first_int(values: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        normalized = _non_negative_int(values.get(key))
        if normalized is not None:
            return normalized
    return None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None
