from __future__ import annotations

from typing import Any, Callable

from src.grok_reasoning_effort import grok_reasoning_effort_values
from src.provider_limit_channel import openai_compatible_endpoint_url
from src.provider_limit_result import set_feature, set_value_features
from src.provider_limit_schema import ProbeResult, REASONING_EFFORT_VALUES


PostJsonProbe = Callable[[str, dict[str, str], dict[str, Any]], ProbeResult]


def test_grok_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    test_channel: str,
    post_json_probe: PostJsonProbe,
) -> None:
    if test_channel == "responses":
        _test_grok_responses_limits(result, config, post_json_probe=post_json_probe)
        return
    _test_grok_chat_limits(result, config, post_json_probe=post_json_probe)


def _test_grok_chat_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> None:
    set_feature(result, "access", _probe_grok_chat(config, {}, post_json_probe=post_json_probe))
    set_feature(result, "responses_api", ProbeResult(False, "not available in the chat_completions test channel"))
    set_feature(result, "web_search", ProbeResult(False, "Grok web_search requires the responses test channel"))
    _record_grok_reasoning_features(
        result,
        config,
        probe=lambda effort: _probe_grok_chat(
            config,
            {"reasoning_effort": effort},
            post_json_probe=post_json_probe,
        ),
    )


def _test_grok_responses_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
) -> None:
    access = _probe_grok_responses(config, {}, post_json_probe=post_json_probe)
    set_feature(result, "access", access)
    set_feature(result, "responses_api", access)
    set_feature(
        result,
        "web_search",
        _probe_grok_responses(
            config,
            {"tools": [{"type": "web_search"}]},
            post_json_probe=post_json_probe,
        ),
    )
    _record_grok_reasoning_features(
        result,
        config,
        probe=lambda effort: _probe_grok_responses(
            config,
            {"reasoning": {"effort": effort}},
            post_json_probe=post_json_probe,
        ),
    )


def _record_grok_reasoning_features(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    probe: Callable[[str], ProbeResult],
) -> None:
    set_feature(result, "thinking", ProbeResult(False, "Grok uses reasoning_effort and does not send thinking"))
    supported_efforts = set(grok_reasoning_effort_values(config.get("model")))
    model = str(config.get("model") or "").strip() or "configured model"
    set_value_features(
        result,
        "reasoning_effort",
        {
            effort: (
                probe(effort)
                if effort in supported_efforts
                else ProbeResult(False, f"Grok reasoning_effort '{effort}' is not defined for model '{model}'")
            )
            for effort in REASONING_EFFORT_VALUES
        },
    )


def _probe_grok_chat(
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


def _probe_grok_responses(
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


def _bearer_headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {str(config.get('apiKey') or '')}",
    }
