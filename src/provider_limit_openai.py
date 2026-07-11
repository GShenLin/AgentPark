from __future__ import annotations

from typing import Any, Callable

from src.provider_limit_channel import openai_compatible_endpoint_url
from src.provider_limit_schema import ProbeResult, REASONING_EFFORT_VALUES, THINKING_VALUES


PostJsonProbe = Callable[[str, dict[str, str], dict[str, Any]], ProbeResult]


def test_openai_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    test_channel: str,
    post_json_probe: PostJsonProbe,
) -> None:
    if test_channel == "responses":
        access = _probe_responses(config, {}, post_json_probe=post_json_probe)
        _set_feature(result, "access", access)
        _set_feature(result, "responses_api", access)
        _set_feature(
            result,
            "web_search",
            _probe_responses(config, _web_search_payload(config), post_json_probe=post_json_probe),
        )
        _set_feature(result, "thinking", ProbeResult(False, "OpenAI Responses provider contract does not send thinking"))
        _set_value_features(
            result,
            "reasoning_effort",
            {
                effort: _probe_responses(
                    config,
                    {"reasoning": {"effort": effort}},
                    post_json_probe=post_json_probe,
                )
                for effort in REASONING_EFFORT_VALUES
            },
        )
        return

    _set_feature(result, "access", _probe_chat_completions(config, {}, post_json_probe=post_json_probe))
    _set_feature(result, "responses_api", ProbeResult(False, "not available in the chat_completions test channel"))
    _set_feature(result, "web_search", ProbeResult(False, "OpenAI web_search requires the responses test channel"))
    _set_value_features(
        result,
        "thinking",
        {
            mode: _probe_chat_completions(
                config,
                {"thinking": {"type": mode}},
                post_json_probe=post_json_probe,
            )
            for mode in THINKING_VALUES
        },
    )
    _set_value_features(
        result,
        "reasoning_effort",
        {
            effort: _probe_chat_completions(
                config,
                {"reasoning_effort": effort},
                post_json_probe=post_json_probe,
            )
            for effort in REASONING_EFFORT_VALUES
        },
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
    return post_json_probe(
        openai_compatible_endpoint_url(config, "chat_completions"),
        _bearer_headers(config),
        payload,
    )


def _probe_responses(
    config: dict[str, Any],
    extra_payload: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply exactly OK."}]}],
        **extra_payload,
    }
    return post_json_probe(
        openai_compatible_endpoint_url(config, "responses"),
        _bearer_headers(config),
        payload,
    )


def _web_search_payload(config: dict[str, Any]) -> dict[str, Any]:
    tool_type = str(config.get("webSearchToolType", "web_search") or "").strip()
    return {"tools": [{"type": tool_type or "web_search"}]}


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
