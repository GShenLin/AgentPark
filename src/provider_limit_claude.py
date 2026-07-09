from __future__ import annotations

from typing import Any, Callable

from src.provider_limit_schema import REASONING_EFFORT_VALUES
from src.provider_limit_schema import ProbeResult


PostJsonProbe = Callable[[str, dict[str, str], dict[str, Any]], ProbeResult]


def test_claude_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    timeout_seconds: float,
    post_json_probe: PostJsonProbe,
) -> None:
    access = _probe_claude_messages(config, {}, post_json_probe=post_json_probe)
    _set_feature(result, "access", access)
    _set_feature(result, "responses_api", ProbeResult(False, "Claude uses the native Messages API, not OpenAI Responses API"))
    _set_feature(result, "web_search", _probe_claude_messages(config, {"tools": [_claude_web_search_tool(config)]}, post_json_probe=post_json_probe))
    _set_value_features(
        result,
        "thinking",
        {
            "enabled": _probe_claude_messages(
                config,
                {"thinking": {"type": "enabled", "budget_tokens": 1024}, "max_tokens": 2048},
                post_json_probe=post_json_probe,
            ),
            "disabled": _probe_claude_messages(config, {}, post_json_probe=post_json_probe),
            "auto": _probe_claude_messages(config, {"thinking": {"type": "adaptive"}}, post_json_probe=post_json_probe),
        },
    )
    _set_value_features(
        result,
        "reasoning_effort",
        {
            effort: (
                _probe_claude_messages(config, {"output_config": {"effort": effort}}, post_json_probe=post_json_probe)
                if effort in {"low", "medium", "high", "xhigh", "max"}
                else ProbeResult(False, "Claude output_config.effort supports low, medium, high, xhigh, and max")
            )
            for effort in REASONING_EFFORT_VALUES
        },
    )


def _probe_claude_messages(config: dict[str, Any], extra_payload: dict[str, Any], *, post_json_probe: PostJsonProbe) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "Reply exactly OK."}],
        **extra_payload,
    }
    return post_json_probe(_claude_messages_url(config), _claude_headers(config), payload)


def _claude_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": str(config.get("apiKey") or ""),
        "anthropic-version": str(config.get("anthropicVersion") or "2023-06-01"),
    }
    beta = str(config.get("anthropicBeta") or "").strip()
    if beta:
        headers["anthropic-beta"] = beta
    return headers


def _claude_messages_url(config: dict[str, Any]) -> str:
    base_url = str(config.get("baseUrl") or "").strip().rstrip("/")
    if base_url.endswith("/messages"):
        return base_url
    return f"{base_url}/messages"


def _claude_web_search_tool(config: dict[str, Any]) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": str(config.get("webSearchToolType") or "web_search_20260318"),
        "name": "web_search",
    }
    limit = config.get("webSearchLimit")
    if isinstance(limit, int) and limit > 0:
        tool["max_uses"] = limit
    return tool


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
