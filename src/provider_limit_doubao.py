from __future__ import annotations

from typing import Any, Callable

from src.provider_limit_schema import REASONING_EFFORT_VALUES
from src.provider_limit_schema import THINKING_VALUES
from src.provider_limit_schema import ProbeResult


PostJsonProbe = Callable[[str, dict[str, str], dict[str, Any]], ProbeResult]


def test_doubao_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    timeout_seconds: float,
    post_json_probe: PostJsonProbe,
) -> None:
    _ = timeout_seconds
    access = _probe_doubao_responses(config, {}, post_json_probe=post_json_probe)
    _set_feature(result, "access", access)
    _set_feature(result, "responses_api", access)
    _set_feature(result, "web_search", _probe_doubao_responses(config, _doubao_web_search_payload(config), post_json_probe=post_json_probe))
    _set_value_features(
        result,
        "thinking",
        {
            mode: _probe_doubao_responses(config, {"thinking": {"type": mode}}, post_json_probe=post_json_probe)
            for mode in THINKING_VALUES
        },
    )
    _set_value_features(
        result,
        "reasoning_effort",
        {
            effort: (
                _probe_doubao_responses(config, {"reasoning": {"effort": effort}}, post_json_probe=post_json_probe)
                if effort in {"low", "medium", "high"}
                else ProbeResult(False, "Doubao Ark Responses reasoning.effort supports low, medium, and high")
            )
            for effort in REASONING_EFFORT_VALUES
        },
    )


def _probe_doubao_responses(config: dict[str, Any], extra_payload: dict[str, Any], *, post_json_probe: PostJsonProbe) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply exactly OK."}]}],
        **extra_payload,
    }
    return post_json_probe(_doubao_responses_url(config), _bearer_headers(config), payload)


def _doubao_responses_url(config: dict[str, Any]) -> str:
    base_url = str(config.get("baseUrl") or "").strip().rstrip("/")
    if base_url.endswith("/responses"):
        return base_url
    return f"{base_url}/responses"


def _bearer_headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {str(config.get('apiKey') or '')}",
    }


def _doubao_web_search_payload(config: dict[str, Any]) -> dict[str, Any]:
    tool: dict[str, Any] = {"type": "web_search"}
    for source_key, target_key in (
        ("webSearchMaxKeyword", "max_keyword"),
        ("webSearchLimit", "limit"),
    ):
        value = config.get(source_key)
        if isinstance(value, int) and value > 0:
            tool[target_key] = value
    sources = config.get("webSearchSources")
    if isinstance(sources, list) and sources:
        tool["sources"] = [str(item) for item in sources if str(item or "").strip()]
    return {"tools": [tool]}


def _set_feature(result: dict[str, Any], feature_name: str, probe: ProbeResult) -> None:
    features = result.setdefault("features", {})
    features[feature_name] = probe.to_payload()
    if not probe.supported:
        _record_unsupported(result, feature_name, probe.reason)


def _set_value_features(result: dict[str, Any], feature_name: str, probes: dict[str, ProbeResult]) -> None:
    supported_values = [value for value, probe in probes.items() if probe.supported]
    values_payload = {value: probe.to_payload() for value, probe in probes.items()}
    result.setdefault("features", {})[feature_name] = {
        "supported": bool(supported_values),
        "supported_values": supported_values,
        "values": values_payload,
    }
    unsupported_values = {
        value: probe.reason or "not supported"
        for value, probe in probes.items()
        if not probe.supported
    }
    if unsupported_values:
        result.setdefault("unsupported", {})[feature_name] = unsupported_values


def _record_unsupported(result: dict[str, Any], name: str, reason: str) -> None:
    result.setdefault("unsupported", {})[name] = str(reason or "not supported")
