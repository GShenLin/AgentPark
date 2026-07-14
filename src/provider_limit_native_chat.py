from __future__ import annotations

from typing import Any, Callable

from src.provider_limit_channel import openai_compatible_endpoint_url
from src.provider_limit_result import set_feature, set_value_features
from src.provider_limit_schema import ProbeResult, REASONING_EFFORT_VALUES


PostJsonProbe = Callable[[str, dict[str, str], dict[str, Any]], ProbeResult]


def test_zhipu_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> None:
    access = _probe_chat_completions(config, {}, post_json_probe=post_json_probe)
    set_feature(result, "access", access)
    set_feature(result, "responses_api", ProbeResult(False, "Zhipu provider contract uses chat/completions, not Responses API"))
    set_feature(result, "web_search", ProbeResult(False, "Zhipu provider contract does not send web_search"))
    set_value_features(
        result,
        "thinking",
        {
            "enabled": _probe_chat_completions(config, {"thinking": {"type": "enabled"}}, post_json_probe=post_json_probe),
            "disabled": _probe_chat_completions(config, {"thinking": {"type": "disabled"}}, post_json_probe=post_json_probe),
            "auto": ProbeResult(False, "Zhipu thinking supports enabled/disabled only"),
        },
    )
    set_value_features(
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
    set_feature(result, "access", _probe_gemini_generate_content(config, post_json_probe=post_json_probe))
    set_feature(result, "responses_api", ProbeResult(False, "Gemini provider contract uses generateContent, not Responses API"))
    set_feature(result, "web_search", ProbeResult(False, "Gemini provider contract does not send web_search"))
    set_feature(result, "thinking", ProbeResult(False, "Gemini provider contract does not send thinking"))
    set_value_features(
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
