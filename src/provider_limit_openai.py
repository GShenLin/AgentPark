from __future__ import annotations

from typing import Any, Callable

from src.provider_limit_result import set_feature, set_value_features
from src.provider_limit_schema import ProbeResult, REASONING_EFFORT_VALUES, THINKING_VALUES


PostJsonProbe = Callable[[str, dict[str, str], dict[str, Any]], ProbeResult]
RequestTarget = Callable[[dict[str, Any], str], tuple[str, dict[str, str]]]


def test_openai_limits(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    test_channel: str,
    post_json_probe: PostJsonProbe,
    request_target: RequestTarget,
) -> None:
    if test_channel == "responses":
        access = _probe_responses(config, {}, post_json_probe=post_json_probe, request_target=request_target)
        set_feature(result, "access", access)
        set_feature(result, "responses_api", access)
        set_feature(
            result,
            "web_search",
            _probe_responses(
                config,
                _web_search_payload(config),
                post_json_probe=post_json_probe,
                request_target=request_target,
            ),
        )
        set_feature(result, "thinking", ProbeResult(False, "OpenAI Responses provider contract does not send thinking"))
        set_value_features(
            result,
            "reasoning_effort",
            {
                effort: _probe_responses(
                    config,
                    {"reasoning": {"effort": effort}},
                    post_json_probe=post_json_probe,
                    request_target=request_target,
                )
                for effort in REASONING_EFFORT_VALUES
            },
        )
        return

    set_feature(
        result,
        "access",
        _probe_chat_completions(
            config,
            {},
            post_json_probe=post_json_probe,
            request_target=request_target,
        ),
    )
    set_feature(result, "responses_api", ProbeResult(False, "not available in the chat_completions test channel"))
    set_feature(result, "web_search", ProbeResult(False, "OpenAI web_search requires the responses test channel"))
    set_value_features(
        result,
        "thinking",
        {
            mode: _probe_chat_completions(
                config,
                {"thinking": {"type": mode}},
                post_json_probe=post_json_probe,
                request_target=request_target,
            )
            for mode in THINKING_VALUES
        },
    )
    set_value_features(
        result,
        "reasoning_effort",
        {
            effort: _probe_chat_completions(
                config,
                {"reasoning_effort": effort},
                post_json_probe=post_json_probe,
                request_target=request_target,
            )
            for effort in REASONING_EFFORT_VALUES
        },
    )


def _probe_chat_completions(
    config: dict[str, Any],
    extra_payload: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
    request_target: RequestTarget,
) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "messages": [{"role": "user", "content": "Reply exactly OK."}],
        **extra_payload,
    }
    url, headers = request_target(config, "chat_completions")
    return post_json_probe(url, headers, payload)


def _probe_responses(
    config: dict[str, Any],
    extra_payload: dict[str, Any],
    *,
    post_json_probe: PostJsonProbe,
    request_target: RequestTarget,
) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply exactly OK."}]}],
        **extra_payload,
    }
    if _is_codex_auth_provider(config):
        payload.setdefault("store", False)
        payload.setdefault("stream", True)
    url, headers = request_target(config, "responses")
    return post_json_probe(url, headers, payload)


def _web_search_payload(config: dict[str, Any]) -> dict[str, Any]:
    tool_type = str(config.get("webSearchToolType", "web_search") or "").strip()
    return {"tools": [{"type": tool_type or "web_search"}]}


def _is_codex_auth_provider(config: dict[str, Any]) -> bool:
    return str((config or {}).get("authMode") or "api_key").strip().lower() == "codex"
