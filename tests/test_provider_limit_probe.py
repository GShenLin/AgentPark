import json


class _FakeResponse:
    def __init__(self, body='{"ok": true}', status_code=200):
        self.body = body
        self.status_code = status_code


def test_provider_limit_probe_writes_unsupported_features(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_limit_probe import run_provider_limit_tests

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "test-key",
                        "baseUrl": "https://example.test/v1",
                        "model": "demo-model",
                        "responsesApi": True,
                        "responsesReplayReasoningItems": False,
                        "toolResultSubmissionMaxChars": 50000,
                        "toolContextCompactionEnabled": False,
                        "toolContextCompactionEveryToolCalls": 10,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    def fake_curl_post_once_raw(self, *, url, headers, payload_json, timeout_sec, marker, no_buffer=False):
        _ = self, headers, timeout_sec, marker, no_buffer
        if "/responses" in url and '"effort": "max"' in payload_json:
            return _FakeResponse('{"error":{"message":"unsupported effort"}}', 400)
        return _FakeResponse()

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_post_once_raw", fake_curl_post_once_raw)

    result = run_provider_limit_tests(timeout_seconds=1)

    assert result["path"].endswith("ProviderLimit.json")
    provider = result["providers"]["demo"]
    assert provider["accessible"] is True
    assert provider["test_channel"] == "responses"
    assert provider["test_endpoint"] == "https://example.test/v1/responses"
    assert set(provider["channels"]) == {"chat_completions", "responses"}
    responses = provider["channels"]["responses"]
    assert responses["features"]["responses_api"]["supported"] is True
    assert responses["features"]["thinking"]["supported"] is False
    assert "does not send thinking" in responses["features"]["thinking"]["reason"]
    assert responses["features"]["reasoning_effort"]["values"]["max"]["supported"] is False
    assert responses["unsupported"]["reasoning_effort"]["max"].startswith("HTTP 400")
    saved = json.loads((config_dir / "ProviderLimit.json").read_text(encoding="utf-8"))
    assert saved["providers"]["demo"]["provider_id"] == "demo"
    assert saved["status"] == "finished"
    assert saved["completed_providers"] == 1
    assert saved["total_providers"] == 1


def test_provider_limit_probe_automatically_tests_openai_chat_and_responses_channels(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_limit_probe import run_provider_limit_tests

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "test-key",
                        "baseUrl": "https://example.test/v1/responses",
                        "model": "demo-model",
                        "responsesApi": True,
                        "responsesReplayReasoningItems": False,
                        "toolResultSubmissionMaxChars": 50000,
                        "toolContextCompactionEnabled": False,
                        "toolContextCompactionEveryToolCalls": 10,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    observed = []

    def fake_curl_post_once_raw(self, *, url, headers, payload_json, timeout_sec, marker, no_buffer=False):
        _ = self, headers, timeout_sec, marker, no_buffer
        observed.append((url, json.loads(payload_json)))
        return _FakeResponse()

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_post_once_raw", fake_curl_post_once_raw)

    result = run_provider_limit_tests(timeout_seconds=1)
    provider = result["providers"]["demo"]
    chat_provider = provider["channels"]["chat_completions"]
    responses_provider = provider["channels"]["responses"]

    assert result["test_mode"] == "all_channels"
    assert chat_provider["test_endpoint"] == "https://example.test/v1/chat/completions"
    assert responses_provider["test_endpoint"] == "https://example.test/v1/responses"
    assert {url for url, _payload in observed} == {
        "https://example.test/v1/chat/completions",
        "https://example.test/v1/responses",
    }
    chat_payloads = [payload for url, payload in observed if url.endswith("/chat/completions")]
    responses_payloads = [payload for url, payload in observed if url.endswith("/responses")]
    assert all("messages" in payload and "input" not in payload for payload in chat_payloads)
    assert any(payload.get("thinking") == {"type": "disabled"} for payload in chat_payloads)
    assert all("input" in payload and "messages" not in payload for payload in responses_payloads)
    assert not any("thinking" in payload for payload in responses_payloads)


def test_provider_limit_probe_tests_claude_native_messages_features(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_limit_probe import run_provider_limit_tests

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps(
            {
                "providers": {
                    "claude-demo": {
                        "type": "claude",
                        "apiKey": "test-key",
                        "baseUrl": "https://api.anthropic.test/v1",
                        "model": "claude-demo-model",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    observed_payloads = []

    def fake_curl_post_once_raw(self, *, url, headers, payload_json, timeout_sec, marker, no_buffer=False):
        _ = self, headers, timeout_sec, marker, no_buffer
        observed_payloads.append((url, json.loads(payload_json)))
        if '"type": "adaptive"' in payload_json:
            return _FakeResponse('{"error":{"message":"unsupported adaptive thinking"}}', 400)
        return _FakeResponse()

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_post_once_raw", fake_curl_post_once_raw)

    result = run_provider_limit_tests(timeout_seconds=1)

    provider = result["providers"]["claude-demo"]
    assert provider["accessible"] is True
    assert provider["features"]["responses_api"]["supported"] is False
    assert provider["features"]["web_search"]["supported"] is True
    assert provider["features"]["thinking"]["supported"] is True
    assert provider["features"]["thinking"]["values"]["enabled"]["supported"] is True
    assert provider["features"]["thinking"]["values"]["auto"]["supported"] is False
    assert provider["features"]["reasoning_effort"]["values"]["high"]["supported"] is True
    assert provider["features"]["reasoning_effort"]["values"]["xhigh"]["supported"] is True
    assert provider["features"]["reasoning_effort"]["values"]["max"]["supported"] is True
    assert provider["unsupported"]["thinking"]["auto"].startswith("HTTP 400")
    assert {url for url, _payload in observed_payloads} == {"https://api.anthropic.test/v1/messages"}
    assert any(payload.get("output_config") == {"effort": "high"} for _url, payload in observed_payloads)
    assert any(payload.get("output_config") == {"effort": "xhigh"} for _url, payload in observed_payloads)
    assert any(payload.get("output_config") == {"effort": "max"} for _url, payload in observed_payloads)
    assert any(payload.get("tools") == [{"type": "web_search_20260318", "name": "web_search"}] for _url, payload in observed_payloads)
    assert not any("/responses" in url for url, _payload in observed_payloads)


def test_provider_limit_probe_tests_doubao_ark_responses_features(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_limit_probe import run_provider_limit_tests

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps(
            {
                "providers": {
                    "doubao-demo": {
                        "type": "doubao",
                        "apiKey": "test-key",
                        "baseUrl": "https://ark.test/api/v3",
                        "model": "doubao-demo-model",
                        "responsesApi": True,
                        "toolResultSubmissionMaxChars": 50000,
                        "toolContextCompactionEnabled": False,
                        "toolContextCompactionEveryToolCalls": 10,
                        "webSearchMaxKeyword": 2,
                        "webSearchLimit": 3,
                        "webSearchSources": ["toutiao"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    observed_payloads = []

    def fake_curl_post_once_raw(self, *, url, headers, payload_json, timeout_sec, marker, no_buffer=False):
        _ = self, headers, timeout_sec, marker, no_buffer
        payload = json.loads(payload_json)
        observed_payloads.append((url, payload))
        if payload.get("thinking", {}).get("type") == "auto":
            return _FakeResponse('{"error":{"message":"unsupported auto thinking"}}', 400)
        if payload.get("reasoning", {}).get("effort") in {"xhigh", "max"}:
            return _FakeResponse('{"error":{"message":"unknown effort"}}', 400)
        return _FakeResponse()

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_post_once_raw", fake_curl_post_once_raw)

    result = run_provider_limit_tests(timeout_seconds=1)

    provider = result["providers"]["doubao-demo"]
    assert provider["accessible"] is True
    assert provider["features"]["responses_api"]["supported"] is True
    assert provider["features"]["web_search"]["supported"] is True
    assert provider["features"]["thinking"]["values"]["enabled"]["supported"] is True
    assert provider["features"]["thinking"]["values"]["auto"]["supported"] is False
    assert provider["features"]["reasoning_effort"]["values"]["high"]["supported"] is True
    assert provider["features"]["reasoning_effort"]["values"]["xhigh"]["supported"] is False
    assert {url for url, _payload in observed_payloads} == {
        "https://ark.test/api/v3/chat/completions",
        "https://ark.test/api/v3/responses",
    }
    assert any(payload.get("tools") == [{"type": "web_search", "max_keyword": 2, "limit": 3, "sources": ["toutiao"]}] for _url, payload in observed_payloads)
    assert any(payload.get("thinking") == {"type": "enabled"} for _url, payload in observed_payloads)
    assert any(payload.get("reasoning") == {"effort": "high"} for _url, payload in observed_payloads)
    assert any("/chat/completions" in url for url, _payload in observed_payloads)


def test_provider_limit_probe_records_missing_required_config(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_limit_probe import run_provider_limit_tests

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps({"providers": {"bad": {"type": "openai", "baseUrl": "https://example.test/v1", "model": "x"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    result = run_provider_limit_tests(timeout_seconds=1)

    provider = result["providers"]["bad"]
    assert provider["accessible"] is False
    assert provider["status"] == "unavailable"
    assert "apiKey" in provider["access_error"]


def test_provider_limit_probe_updates_file_after_each_provider(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_limit_probe import run_provider_limit_tests

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps(
            {
                "providers": {
                    "first": {"type": "openai", "baseUrl": "https://example.test/v1", "model": "x"},
                    "second": {"type": "openai", "baseUrl": "https://example.test/v1", "model": "y"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    observed_snapshots = []

    def on_progress(payload):
        if payload.get("provider_id") == "first" and payload.get("status") == "finished":
            saved = json.loads((config_dir / "ProviderLimit.json").read_text(encoding="utf-8"))
            observed_snapshots.append(saved)

    result = run_provider_limit_tests(timeout_seconds=1, progress_callback=on_progress)

    assert observed_snapshots
    first_snapshot = observed_snapshots[0]
    assert first_snapshot["status"] == "running"
    assert first_snapshot["completed_providers"] == 1
    assert first_snapshot["total_providers"] == 2
    assert list(first_snapshot["providers"].keys()) == ["first"]
    assert result["status"] == "finished"
    assert result["completed_providers"] == 2


def test_provider_model_discovery_writes_available_models(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_model_discovery import run_provider_model_discovery

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "test-key",
                        "baseUrl": "https://example.test/v1",
                        "model": "demo-model",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    def fake_curl_get_text_once_raw(self, *, url, headers, timeout_sec, marker):
        _ = self, headers, timeout_sec, marker
        assert url == "https://example.test/v1/models"
        return _FakeResponse(json.dumps({"data": [{"id": "demo-model"}, {"id": "next-model"}]}))

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_get_text_once_raw", fake_curl_get_text_once_raw)

    result = run_provider_model_discovery(timeout_seconds=1)

    provider = result["providers"]["demo"]
    assert provider["accessible"] is True
    assert provider["available_model_ids"] == ["demo-model", "next-model"]
    assert provider["model_discovery"]["supported"] is True
    assert result["model_refresh_status"] == "finished"
    saved = json.loads((config_dir / "ProviderLimit.json").read_text(encoding="utf-8"))
    assert saved["providers"]["demo"]["available_model_ids"] == ["demo-model", "next-model"]


def test_provider_model_discovery_strips_gemini_model_prefix(monkeypatch, tmp_path):
    from src import workspace_settings
    from src.provider_model_discovery import run_provider_model_discovery

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moduleProvider.json").write_text(
        json.dumps(
            {
                "providers": {
                    "gem": {
                        "type": "gemini",
                        "apiKey": "test-key",
                        "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
                        "model": "gemini-3-pro-preview",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_dir / "moduleProvider.json"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    def fake_curl_get_text_once_raw(self, *, url, headers, timeout_sec, marker):
        _ = self, url, headers, timeout_sec, marker
        return _FakeResponse(json.dumps({"models": [{"name": "models/gemini-3-pro-preview"}]}))

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_get_text_once_raw", fake_curl_get_text_once_raw)

    result = run_provider_model_discovery(timeout_seconds=1)

    assert result["providers"]["gem"]["available_model_ids"] == ["gemini-3-pro-preview"]
