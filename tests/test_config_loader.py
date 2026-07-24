import json

import pytest

from src.config_loader import ConfigLoader


def _reset_loader_singleton():
    ConfigLoader._instance = None


def _responses_contract(**overrides):
    payload = {
        "responsesApi": True,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
        "toolContextCompactionInputTokens": 0,
        "toolContextCompactionCurrentInputTokens": 0,
        "toolContextCompactionOutputTokens": 0,
    }
    payload.update(overrides)
    return payload


def _write_openai_responses_provider(tmp_path, **contract_overrides):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "test-key",
                        "model": "gpt-test",
                        **_responses_contract(**contract_overrides),
                        "responsesReplayReasoningItems": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("", ""),
        ("speech-key", "speech-key"),
    ],
)
def test_provider_x_api_key_accepts_key_name_references(monkeypatch, tmp_path, configured, expected):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "demo": {
                    "type": "doubao",
                    "apiKey": "general-key",
                    "xApiKey": configured,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    providers = ConfigLoader().get_all_providers()

    assert providers["demo"]["xApiKey"] == expected


def test_provider_x_api_key_rejects_key_name_with_surrounding_whitespace(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "demo": {
                    "type": "doubao",
                    "apiKey": "general-key",
                    "xApiKey": "  speech-key  ",
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="surrounding whitespace"):
        ConfigLoader().get_all_providers()


def test_provider_x_api_key_rejects_non_string(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "demo": {
                    "type": "doubao",
                    "apiKey": "general-key",
                    "xApiKey": 123,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="xApiKey"):
        ConfigLoader().get_all_providers()


@pytest.mark.parametrize("key", ["speechAccessKeyId", "speechSecretAccessKey"])
def test_provider_speech_access_key_fields_accept_key_name_references(monkeypatch, tmp_path, key):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "demo": {
                    "type": "doubao",
                    "apiKey": "general-key",
                    key: "speech-credential",
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    assert ConfigLoader().get_all_providers()["demo"][key] == "speech-credential"


@pytest.mark.parametrize("key", ["speechAccessKeyId", "speechSecretAccessKey"])
def test_provider_speech_access_key_fields_reject_non_string(monkeypatch, tmp_path, key):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "demo": {
                    "type": "doubao",
                    "apiKey": "general-key",
                    key: 123,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match=key):
        ConfigLoader().get_all_providers()


@pytest.mark.parametrize(
    "missing_key",
    [
        "toolContextCompactionInputTokens",
        "toolContextCompactionCurrentInputTokens",
        "toolContextCompactionOutputTokens",
    ],
)
def test_responses_provider_requires_token_compaction_limits(monkeypatch, tmp_path, missing_key):
    contract = _responses_contract()
    contract.pop(missing_key)
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "test-key",
                        "model": "gpt-test",
                        **contract,
                        "responsesReplayReasoningItems": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match=missing_key):
        ConfigLoader().get_config()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("toolContextCompactionEveryToolCalls", -1),
        ("toolContextCompactionInputTokens", -1),
        ("toolContextCompactionCurrentInputTokens", -1),
        ("toolContextCompactionOutputTokens", True),
    ],
)
def test_responses_provider_rejects_invalid_compaction_limits(
    monkeypatch,
    tmp_path,
    field_name,
    value,
):
    config_path = _write_openai_responses_provider(tmp_path, **{field_name: value})
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match=field_name):
        ConfigLoader().get_config()


def test_responses_provider_rejects_enabled_compaction_with_all_limits_zero(monkeypatch, tmp_path):
    config_path = _write_openai_responses_provider(
        tmp_path,
        toolContextCompactionEnabled=True,
        toolContextCompactionEveryToolCalls=0,
        toolContextCompactionInputTokens=0,
        toolContextCompactionCurrentInputTokens=0,
        toolContextCompactionOutputTokens=0,
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="all compaction limits are zero"):
        ConfigLoader().get_config()


def test_responses_provider_accepts_context_window_compaction_policy(monkeypatch, tmp_path):
    config_path = _write_openai_responses_provider(
        tmp_path,
        toolContextCompactionEnabled=True,
        toolContextCompactionEveryToolCalls=0,
        toolContextCompactionCurrentInputTokens=0,
        modelContextWindowTokens=272_000,
        toolContextCompactionContextPercent=90,
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    provider = ConfigLoader().get_config()["providers"]["demo"]

    assert provider["modelContextWindowTokens"] == 272_000
    assert provider["toolContextCompactionContextPercent"] == 90


@pytest.mark.parametrize(
    "overrides",
    [
        {"toolContextCompactionContextPercent": 90},
        {
            "modelContextWindowTokens": 272_000,
            "toolContextCompactionContextPercent": 0,
        },
        {
            "modelContextWindowTokens": 272_000,
            "toolContextCompactionContextPercent": 101,
        },
        {
            "modelContextWindowTokens": 272_000,
            "toolContextCompactionContextPercent": 90,
            "toolContextCompactionCurrentInputTokens": 50_000,
        },
    ],
)
def test_responses_provider_rejects_invalid_context_window_compaction_policy(
    monkeypatch,
    tmp_path,
    overrides,
):
    config_path = _write_openai_responses_provider(tmp_path, **overrides)
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError):
        ConfigLoader().get_config()


def test_get_config_returns_validated_payload_and_supports_explicit_config_path(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "supportmode": ["chat", "imagechat"],
                        "timeoutMs": 1500,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "server": {"host": "0.0.0.0", "port": 8788},
                "agentNode": {"minSendDelayMs": 120, "historyMessageLimit": 12},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    loader = ConfigLoader()
    payload = loader.get_config()

    assert payload["agentNode"]["minSendDelayMs"] == 120
    assert payload["agentNode"]["historyMessageLimit"] == 12
    assert payload["server"]["port"] == 8788
    assert payload["providers"]["demo"]["type"] == "gemini"
    assert payload["providers"]["demo"]["supportmode"] == ["chat", "imagechat"]
    assert payload["providers"]["demo"]["timeoutMs"] == 1500
    assert payload["providers"]["demo"]["apiKey"] == "inline-secret"
    assert payload["providers"]["demo"]["private"] is False
    assert payload["providers"]["demo"]["features"]["web_search"]["supported"] is False
    assert payload["providers"]["demo"]["features"]["thinking"]["supported"] is False


def test_get_config_preserves_private_provider_option(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "private": True,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    assert ConfigLoader().get_config()["providers"]["demo"]["private"] is True


def test_get_config_rejects_non_boolean_private_provider_option(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "private": "true",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="invalid private"):
        ConfigLoader().get_config()


def test_get_config_rejects_provider_type_case_normalization(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "Gemini",
                        "apiKey": "inline-secret",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="lowercase string"):
        ConfigLoader().get_config()


def test_get_config_rejects_numeric_string_timeout(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "timeoutMs": "1500",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="positive integer"):
        ConfigLoader().get_config()


def test_get_config_rejects_duplicate_support_modes(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "supportmode": ["chat", "chat"],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="duplicate value"):
        ConfigLoader().get_config()


def test_get_provider_config_requires_non_empty_api_key(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "doubao",
                        "apiKey": "   ",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    loader = ConfigLoader()

    providers = loader.get_all_providers()
    assert providers["demo"]["apiKey"] == ""

    with pytest.raises(ValueError, match="non-empty apiKey"):
        loader.get_provider_config("demo")


def test_get_provider_config_resolves_api_key_name(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "doubao",
                        "apiKey": "inline-secret",
                        "supportmode": [],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    payload = ConfigLoader().get_provider_config("demo")

    assert payload["apiKey"] == "inline-secret"
    assert payload["type"] == "doubao"


def test_openai_codex_auth_does_not_require_api_key(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "official": {
                    "type": "openai",
                    "authMode": "codex",
                    "responsesApi": True,
                    "model": "gpt-test",
                    **_responses_contract(),
                    "responsesReplayReasoningItems": False,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    provider = ConfigLoader().get_provider_config("official")

    assert provider["authMode"] == "codex"
    assert provider["baseUrl"] == "https://chatgpt.com/backend-api/codex"
    assert "apiKey" not in provider


def test_openai_api_key_responses_provider_accepts_fast_mode(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "compatible": {
                    "type": "openai",
                    "apiKey": "test-key",
                    "model": "gpt-test",
                    "fastMode": True,
                    **_responses_contract(),
                    "responsesReplayReasoningItems": False,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    provider = ConfigLoader().get_provider_config("compatible")

    assert provider["authMode"] == "api_key"
    assert provider["fastMode"] is True


@pytest.mark.parametrize("value", ["true", 1, None])
def test_provider_rejects_non_boolean_fast_mode(monkeypatch, tmp_path, value):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "bad": {
                    "type": "openai",
                    "apiKey": "test-key",
                    "fastMode": value,
                    **_responses_contract(),
                    "responsesReplayReasoningItems": False,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="invalid fastMode"):
        ConfigLoader().get_provider_config("bad")


def test_provider_rejects_fast_mode_for_chat_completions(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "bad": {
                    "type": "openai",
                    "apiKey": "test-key",
                    "responsesApi": False,
                    "fastMode": True,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="only with type 'openai' and responsesApi=true"):
        ConfigLoader().get_provider_config("bad")


def test_openai_codex_auth_allows_chat_completions_configuration(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({
            "providers": {
                "official-chat": {
                    "type": "openai",
                    "authMode": "codex",
                    "responsesApi": False,
                    "model": "gpt-test",
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    provider = ConfigLoader().get_provider_config("official-chat")

    assert provider["authMode"] == "codex"
    assert provider["responsesApi"] is False
    assert provider["baseUrl"] == "https://chatgpt.com/backend-api/codex"
    assert "apiKey" not in provider


def test_codex_auth_rejects_non_openai_provider(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps({"providers": {"bad": {"type": "gemini", "authMode": "codex", "responsesApi": True}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="only with type 'openai'"):
        ConfigLoader().get_provider_config("bad")


def test_get_provider_config_is_not_blocked_by_another_invalid_provider(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "valid": {"type": "openai", "apiKey": "valid-key"},
                    "bad": {"type": "gemini", "authMode": "codex", "responsesApi": True},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    provider = ConfigLoader().get_provider_config("valid")

    assert provider["type"] == "openai"
    assert provider["apiKey"] == "valid-key"


def test_doubao_provider_rejects_unsupported_reasoning_effort(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "doubao",
                        "apiKey": "inline-secret",
                        "reasoningEffort": "xhigh",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="reasoning_effort"):
        ConfigLoader().get_provider_config("demo")


def test_doubao_provider_rejects_reasoning_effort_snake_case(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "doubao",
                        "apiKey": "inline-secret",
                        "reasoning_effort": "xhigh",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="unsupported config field"):
        ConfigLoader().get_provider_config("demo")


def test_get_config_rejects_invalid_provider_timeout(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "doubao",
                        "apiKey": "inline-secret",
                        "timeoutMs": 0,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="Provider 'demo' has invalid timeoutMs"):
        ConfigLoader().get_config()


def test_get_config_accepts_provider_pressure_limits(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "inline-secret",
                        "concurrencyLimit": 2,
                        "rpmLimit": 30,
                        "tpmLimit": 1000000,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    provider = ConfigLoader().get_all_providers()["demo"]

    assert provider["concurrencyLimit"] == 2
    assert provider["rpmLimit"] == 30
    assert provider["tpmLimit"] == 1000000


def test_get_config_rejects_invalid_provider_pressure_limits(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "inline-secret",
                        "concurrencyLimit": 0,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="concurrencyLimit"):
        ConfigLoader().get_config()


def test_get_config_reloads_from_disk_when_file_changes(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "model": "model-v1",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    loader = ConfigLoader()
    first = loader.get_provider_config("demo")
    assert first["model"] == "model-v1"

    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "model": "model-v2",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    second = loader.get_provider_config("demo")
    assert second["model"] == "model-v2"


def test_provider_feature_matrix_is_explicit(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {"type": "openai", "apiKey": "openai-key"},
                    "openai-responses": {
                        "type": "openai",
                        "apiKey": "openai-key",
                        **_responses_contract(responsesReplayReasoningItems=False),
                    },
                    "doubao-chat": {"type": "doubao", "apiKey": "doubao-key"},
                    "doubao-responses": {
                        "type": "doubao",
                        "apiKey": "doubao-key",
                        **_responses_contract(),
                    },
                    "zhipu": {"type": "zhipu", "apiKey": "zhipu-key"},
                    "claude": {"type": "claude", "apiKey": "claude-key"},
                    "gemini": {"type": "gemini", "apiKey": "gemini-key"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    providers = ConfigLoader().get_all_providers()

    assert providers["openai"]["features"]["web_search"]["supported"] is False
    assert providers["openai"]["features"]["reasoning_effort"]["supported"] is True
    assert providers["openai"]["features"]["thinking"]["supported"] is True
    assert providers["openai"]["features"]["thinking"]["values"] == ["enabled", "disabled", "auto"]
    assert providers["openai"]["features"]["thinking"]["transport"] == "chat_completions"
    assert providers["openai"]["features"]["responses_api"]["supported"] is False
    assert providers["openai"]["features"]["reasoning_summary"]["supported"] is False
    assert providers["openai"]["features"]["web_search"]["requires"] == "responsesApi=true"
    assert providers["openai-responses"]["features"]["responses_api"]["supported"] is True
    assert providers["openai-responses"]["features"]["thinking"]["supported"] is False
    assert providers["openai-responses"]["features"]["web_search"]["supported"] is True
    assert providers["openai-responses"]["features"]["reasoning_summary"]["values"] == [
        "auto",
        "concise",
        "detailed",
        "disabled",
    ]
    assert providers["doubao-chat"]["features"]["web_search"]["supported"] is False
    assert providers["doubao-chat"]["features"]["web_search"]["requires"] == "responsesApi=true"
    assert providers["doubao-chat"]["features"]["thinking"]["supported"] is False
    assert providers["doubao-responses"]["features"]["web_search"]["supported"] is True
    assert providers["doubao-responses"]["features"]["responses_api"]["supported"] is True
    assert providers["doubao-responses"]["features"]["thinking"]["values"] == ["enabled", "disabled", "auto"]
    assert providers["doubao-responses"]["features"]["reasoning_effort"]["values"] == ["low", "medium", "high"]
    assert providers["zhipu"]["features"]["thinking"]["values"] == ["enabled", "disabled"]
    assert providers["zhipu"]["features"]["reasoning_effort"]["supported"] is True
    assert providers["zhipu"]["features"]["tools"]["supported"] is True
    assert providers["claude"]["features"]["tools"]["supported"] is True
    assert providers["claude"]["features"]["reasoning_effort"]["supported"] is True
    assert providers["claude"]["features"]["reasoning_effort"]["values"] == ["low", "medium", "high", "xhigh", "max"]
    assert providers["gemini"]["features"]["web_search"]["supported"] is False


def test_responses_api_config_requires_boolean(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai",
                        "apiKey": "openai-key",
                        "responsesApi": "true",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    try:
        ConfigLoader().get_all_providers()
    except ValueError as exc:
        assert "responsesApi" in str(exc)
        assert "expected a boolean" in str(exc)
    else:
        raise AssertionError("string responsesApi should fail")


def test_stream_enabled_defaults_to_true_when_absent(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "claude",
                        "apiKey": "claude-key",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    providers = ConfigLoader().get_all_providers()

    assert providers["demo"]["streamEnabled"] is True


def test_stream_enabled_preserves_explicit_false(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "claude",
                        "apiKey": "claude-key",
                        "streamEnabled": False,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    providers = ConfigLoader().get_all_providers()

    assert providers["demo"]["streamEnabled"] is False


def test_stream_enabled_rejects_non_boolean(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "claude",
                        "apiKey": "claude-key",
                        "streamEnabled": "true",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="streamEnabled"):
        ConfigLoader().get_all_providers()


def test_responses_api_provider_requires_explicit_hardening_fields(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai",
                        "apiKey": "openai-key",
                        "responsesApi": True,
                        "toolResultSubmissionMaxChars": 50000,
                        "toolContextCompactionEnabled": True,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="toolContextCompactionEveryToolCalls"):
        ConfigLoader().get_all_providers()


def test_openai_responses_api_provider_requires_reasoning_replay_contract(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai",
                        "apiKey": "openai-key",
                        **_responses_contract(),
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="responsesReplayReasoningItems"):
        ConfigLoader().get_all_providers()


def test_openai_responses_api_provider_validates_reasoning_summary(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai",
                        "apiKey": "openai-key",
                        "reasoningSummary": "verbose",
                        **_responses_contract(responsesReplayReasoningItems=False),
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="reasoningSummary"):
        ConfigLoader().get_all_providers()


def test_grok_45_provider_validates_reasoning_effort(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "grok": {
                        "type": "grok",
                        "apiKey": "grok-key",
                        "model": "grok-4.5",
                        "reasoningEffort": "xhigh",
                        **_responses_contract(responsesReplayReasoningItems=False),
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="Grok 4.5 reasoning_effort"):
        ConfigLoader().get_all_providers()


def test_grok_provider_rejects_reasoning_summary(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "grok": {
                        "type": "grok",
                        "apiKey": "grok-key",
                        "model": "grok-4.5",
                        "reasoningEffort": "high",
                        "reasoningSummary": "auto",
                        **_responses_contract(responsesReplayReasoningItems=False),
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="do not support reasoningSummary"):
        ConfigLoader().get_all_providers()


def test_responses_api_provider_validates_field_types(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai",
                        "apiKey": "openai-key",
                        **_responses_contract(
                            responsesReplayReasoningItems=False,
                            toolContextCompactionEnabled="yes",
                        ),
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="toolContextCompactionEnabled"):
        ConfigLoader().get_all_providers()


def test_deepseek_provider_rejects_responses_api(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "deepseek": {
                        "type": "deepseek",
                        "apiKey": "deepseek-key",
                        "baseUrl": "https://api.deepseek.test",
                        "model": "deepseek-test",
                        "responsesApi": True,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="DeepSeek uses chat completions"):
        ConfigLoader().get_all_providers()


def test_kimi_provider_rejects_responses_api(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "kimi": {
                        "type": "kimi",
                        "apiKey": "kimi-key",
                        "baseUrl": "https://api.moonshot.cn/v1",
                        "model": "kimi-k3",
                        "responsesApi": True,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    with pytest.raises(ValueError, match="Kimi uses chat completions"):
        ConfigLoader().get_all_providers()


def test_agent_domain_lists_provider_features(monkeypatch):
    from src.provider_options import build_provider_support_list

    providers = build_provider_support_list(
        {
            "zhipu": {
                "supportmode": ["chat"],
                "features": {
                    "thinking": {"supported": True, "values": ["enabled", "disabled"]},
                },
            }
        }
    )

    assert providers == [
        {
            "id": "zhipu",
            "supportmode": ["chat"],
            "features": {
                "thinking": {"supported": True, "values": ["enabled", "disabled"]},
            },
        }
    ]
