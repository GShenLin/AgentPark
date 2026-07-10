from src.provider_feature_matrix import (
    PROVIDER_FEATURE_SCHEMA_VERSION,
    build_provider_feature_matrix,
)


def _feature(supported, values, **extra):
    payload = {"supported": supported, "values": values}
    payload.update(extra)
    return payload


def _matrix(**features):
    return {"schema_version": PROVIDER_FEATURE_SCHEMA_VERSION, **features}


def test_provider_feature_matrix_covers_all_supported_provider_transports():
    assert build_provider_feature_matrix({"type": "openai"}) == _matrix(
        responses_api=_feature(False, ["enabled", "disabled"], requires="responsesApi=true", transport="responses"),
        web_search=_feature(False, ["enabled", "disabled"], requires="responsesApi=true"),
        tools=_feature(True, ["enabled", "disabled"]),
        thinking=_feature(False, []),
        reasoning_effort=_feature(True, ["minimal", "low", "medium", "high", "xhigh"]),
        reasoning_summary=_feature(False, [], requires="responsesApi=true"),
    )

    assert build_provider_feature_matrix({"type": "openai", "responsesApi": True}) == _matrix(
        responses_api=_feature(True, ["enabled", "disabled"], requires="responsesApi=true", transport="responses"),
        web_search=_feature(True, ["enabled", "disabled"], requires="responsesApi=true", transport="responses"),
        tools=_feature(True, ["enabled", "disabled"]),
        thinking=_feature(False, []),
        reasoning_effort=_feature(True, ["minimal", "low", "medium", "high", "xhigh"]),
        reasoning_summary=_feature(
            True,
            ["auto", "concise", "detailed", "disabled"],
            requires="responsesApi=true",
            transport="responses",
        ),
    )

    assert build_provider_feature_matrix({"type": "doubao"}) == _matrix(
        responses_api=_feature(False, ["enabled", "disabled"], requires="responsesApi=true"),
        web_search=_feature(False, ["enabled", "disabled"], requires="responsesApi=true"),
        tools=_feature(True, ["enabled", "disabled"]),
        thinking=_feature(False, [], requires="responsesApi=true"),
        reasoning_effort=_feature(False, [], requires="responsesApi=true"),
        reasoning_summary=_feature(False, []),
    )

    assert build_provider_feature_matrix({"type": "doubao", "responsesApi": True}) == _matrix(
        responses_api=_feature(True, ["enabled", "disabled"], requires="responsesApi=true", transport="responses"),
        web_search=_feature(True, ["enabled", "disabled"], requires="responsesApi=true", transport="responses"),
        tools=_feature(True, ["enabled", "disabled"]),
        thinking=_feature(True, ["enabled", "disabled", "auto"], requires="responsesApi=true", transport="responses"),
        reasoning_effort=_feature(True, ["low", "medium", "high"], requires="responsesApi=true", transport="responses"),
        reasoning_summary=_feature(False, []),
    )

    assert build_provider_feature_matrix({"type": "zhipu"}) == _matrix(
        responses_api=_feature(False, []),
        web_search=_feature(False, []),
        tools=_feature(True, ["enabled", "disabled"]),
        thinking=_feature(True, ["enabled", "disabled"]),
        reasoning_effort=_feature(True, ["minimal", "low", "medium", "high", "xhigh"]),
        reasoning_summary=_feature(False, []),
    )

    assert build_provider_feature_matrix({"type": "claude"}) == _matrix(
        responses_api=_feature(False, []),
        web_search=_feature(True, ["enabled", "disabled"], transport="messages"),
        tools=_feature(True, ["enabled", "disabled"]),
        thinking=_feature(True, ["enabled", "disabled", "auto"], transport="messages"),
        reasoning_effort=_feature(True, ["low", "medium", "high", "xhigh", "max"], transport="messages"),
        reasoning_summary=_feature(False, []),
    )

    assert build_provider_feature_matrix({"type": "gemini"}) == _matrix(
        responses_api=_feature(False, []),
        web_search=_feature(False, []),
        tools=_feature(True, ["enabled", "disabled"]),
        thinking=_feature(False, []),
        reasoning_effort=_feature(False, []),
        reasoning_summary=_feature(False, []),
    )


def test_provider_feature_matrix_returns_closed_shape_for_unknown_or_missing_provider_type():
    expected = _matrix(
        responses_api=_feature(False, []),
        web_search=_feature(False, []),
        tools=_feature(False, []),
        thinking=_feature(False, []),
        reasoning_effort=_feature(False, []),
        reasoning_summary=_feature(False, []),
    )

    assert build_provider_feature_matrix(None) == expected
    assert build_provider_feature_matrix({}) == expected
    assert build_provider_feature_matrix({"type": "unknown"}) == expected


def test_provider_feature_matrix_ignores_current_configuration_values():
    noisy_config = {
        "apiKey": "secret",
        "baseUrl": "https://example.invalid/v1",
        "model": "model-from-config",
        "supportmode": ["chat", "imagechat"],
        "streamEnabled": False,
        "timeoutMs": 12345,
        "concurrencyLimit": 2,
        "rpmLimit": 60,
        "tools": "disabled",
        "webSearch": "enabled",
        "webSearchSources": ["web"],
        "webSearchMaxKeyword": 4,
        "webSearchLimit": 8,
        "thinking": "auto",
        "reasoningEffort": "xhigh",
        "reasoningSummary": "detailed",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 3,
        "features": {"web_search": {"supported": False, "values": ["injected"]}},
    }

    for provider_type in ("openai", "doubao", "zhipu", "claude", "gemini"):
        assert build_provider_feature_matrix({"type": provider_type, **noisy_config}) == build_provider_feature_matrix(
            {"type": provider_type}
        )

    for provider_type in ("openai", "doubao"):
        assert build_provider_feature_matrix(
            {"type": provider_type, "responsesApi": True, **noisy_config}
        ) == build_provider_feature_matrix({"type": provider_type, "responsesApi": True})


def test_provider_feature_matrix_only_strict_responses_api_true_enables_responses_transport():
    for provider_type in ("openai", "doubao"):
        chat_transport = build_provider_feature_matrix({"type": provider_type})
        responses_transport = build_provider_feature_matrix({"type": provider_type, "responsesApi": True})

        assert build_provider_feature_matrix({"type": provider_type, "responsesApi": False}) == chat_transport
        assert build_provider_feature_matrix({"type": provider_type, "responsesApi": "true"}) == chat_transport
        assert build_provider_feature_matrix({"type": provider_type, "responsesApi": 1}) == chat_transport
        assert responses_transport != chat_transport
        assert responses_transport["responses_api"] == _feature(
            True,
            ["enabled", "disabled"],
            requires="responsesApi=true",
            transport="responses",
        )
        assert responses_transport["web_search"] == _feature(
            True,
            ["enabled", "disabled"],
            requires="responsesApi=true",
            transport="responses",
        )

    assert build_provider_feature_matrix({"type": "zhipu", "responsesApi": True}) == build_provider_feature_matrix(
        {"type": "zhipu"}
    )
    assert build_provider_feature_matrix({"type": "claude", "responsesApi": True}) == build_provider_feature_matrix(
        {"type": "claude"}
    )
    assert build_provider_feature_matrix({"type": "gemini", "responsesApi": True}) == build_provider_feature_matrix(
        {"type": "gemini"}
    )

