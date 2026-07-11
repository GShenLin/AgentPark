from __future__ import annotations

from typing import Any, Callable

from src.provider_limit_channel import openai_compatible_endpoint_url
from src.provider_limit_schema import ProbeResult, REASONING_EFFORT_VALUES


PostJsonProbe = Callable[[str, dict[str, str], dict[str, Any]], ProbeResult]


def test_zhipu_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> None:
    access = _probe_chat_completions(config, {}, post_json_probe=post_json_probe)
    _set_feature(result, "access", access)
    _set_feature(result, "responses_api", ProbeResult(False, "Zhipu provider contract uses chat/completions, not Responses API"))
    _set_feature(result, "web_search", ProbeResult(False, "Zhipu provider contract does not send web_search"))
    _set_value_features(
        result,
        "thinking",
        {
            "enabled": _probe_chat_completions(config, {"thinking": {"type": "enabled"}}, post_json_probe=post_json_probe),
            "disabled": _probe_chat_completions(config, {"thinking": {"type": "disabled"}}, post_json_probe=post_json_probe),
            "auto": ProbeResult(False, "Zhipu thinking supports enabled/disabled only"),
        },
    )
    _set_value_features(
        result,
        "reasoning_effort",
        {
            effort: _probe_chat_completions(config, {"reasoning_effort": effort}, post_json_probe=post_json_probe)
            for effort in REASONING_EFFORT_VALUES
        },
    )


def test_gemini_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> None:
    _set_feature(result, "access", _probe_gemini_generate_content(config, post_json_probe=post_json_probe))
    _set_feature(result, "responses_api", ProbeResult(False, "Gemini provider contract uses generateContent, not Responses API"))
    _set_feature(result, "web_search", ProbeResult(False, "Gemini provider contract does not send web_search"))
    _set_feature(result, "thinking", ProbeResult(False, "Gemini provider contract does not send thinking"))
    _set_value_features(
        result,
        "reasoning_effort",
        {effort: ProbeResult(False, "Gemini provider contract does not send reasoning_effort") for effort in REASONING_EFFORT_VALUES},
    )


def _probe_chat_completions(
    config: dict[str, Any],
    extra_payload: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "messages": [{"role": "user", "content": "Reply exactly OK."}],
        **extra_payload,
    }
    return post_json_probe(openai_compatible_endpoint_url(config, "chat_completions"), _bearer_headers(config), payload)


def _probe_gemini_generate_content(
    config: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> ProbeResult:
    payload = {"contents": [{"role": "user", "parts": [{"text": "Reply exactly OK."}]}]}
    url = f"{str(config.get('baseUrl') or '').strip().rstrip('/')}/models/{str(config.get('model') or '').strip()}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": str(config.get("apiKey") or ""),
    }
    return post_json_probe(url, headers, payload)


def _bearer_headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {str(config.get('apiKey') or '')}",
    }


def _set_feature(result: dict[str, Any], feature_name: str, probe: ProbeResult) -> None:
    result.setdefault("features", {})[feature_name] = probe.to_payload()
    if not probe.supported:
        result.setdefault("unsupported", {})[feature_name] = str(probe.reason or "not supported")


def _set_value_features(result: dict[str, Any], feature_name: str, probes: dict[str, ProbeResult]) -> None:
    supported_values = [value for value, probe in probes.items() if probe.supported]
    result.setdefault("features", {})[feature_name] = {
        "supported": bool(supported_values),
        "supported_values": supported_values,
        "values": {value: probe.to_payload() for value, probe in probes.items()},
    }
    unsupported_values = {
        value: probe.reason or "not supported"
        for value, probe in probes.items()
        if not probe.supported
    }
    if unsupported_values:
        result.setdefault("unsupported", {})[feature_name] = unsupported_values
