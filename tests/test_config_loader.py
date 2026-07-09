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
    }
    payload.update(overrides)
    return payload


def test_get_config_returns_validated_payload_and_supports_explicit_config_path(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
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
    assert payload["providers"]["demo"]["features"]["web_search"]["supported"] is False
    assert payload["providers"]["demo"]["features"]["thinking"]["supported"] is False


def test_get_config_rejects_provider_type_case_normalization(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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


def test_get_provider_config_still_accepts_direct_api_key(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
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


def test_doubao_provider_rejects_unsupported_reasoning_effort(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "inline-secret",
                        "concurrencyLimit": 2,
                        "rpmLimit": 30,
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


def test_get_config_rejects_invalid_provider_pressure_limits(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    assert providers["openai"]["features"]["thinking"]["supported"] is False
    assert providers["openai"]["features"]["responses_api"]["supported"] is False
    assert providers["openai"]["features"]["web_search"]["requires"] == "responsesApi=true"
    assert providers["openai-responses"]["features"]["responses_api"]["supported"] is True
    assert providers["openai-responses"]["features"]["web_search"]["supported"] is True
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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
    config_path = tmp_path / "moduleProvider.json"
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


def test_responses_api_provider_validates_field_types(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
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
