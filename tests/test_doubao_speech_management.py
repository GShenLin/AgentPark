import json

import pytest


class _Response:
    status = 200

    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_volcengine_openapi_signs_payload_and_parses_result(monkeypatch):
    from src.providers.volcengine_openapi import VolcengineOpenApi

    captured = {}

    def urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response({"ResponseMetadata": {}, "Result": {"Speakers": []}})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = VolcengineOpenApi(
        access_key_id="ak-id",
        secret_access_key="secret",
        region="cn-beijing",
    ).post_json("ListSpeakers", "2025-05-20", {"ResourceIDs": ["seed-tts-2.0"]})

    request = captured["request"]
    assert "Action=ListSpeakers" in request.full_url
    assert request.get_header("Authorization").startswith("HMAC-SHA256 Credential=ak-id/")
    assert request.get_header("X-content-sha256")
    assert result["Result"]["Speakers"] == []


def test_management_lists_speakers_and_returns_combobox_options(monkeypatch):
    from src.web_backend.doubao_speech_management import DoubaoSpeechManagementDomain

    monkeypatch.setattr("src.web_backend.doubao_speech_management.ConfigLoader.get_provider_config", lambda *_args: {
        "type": "doubao",
        "apiKey": "speech-key",
        "speechAccessKeyId": "ak-id",
        "speechSecretAccessKey": "secret",
        "timeoutMs": 60000,
    })
    requests = []
    indexed = {}

    def post_json(_client, _action, _version, payload):
        requests.append(payload)
        page = payload["Page"]
        speakers = (
            [{"VoiceType": "speaker-1", "Name": "Speaker One"}]
            if page == 1
            else [{"VoiceType": "speaker-2", "Name": ""}]
        )
        return {"ResponseMetadata": {}, "Result": {"Speakers": speakers, "Total": 2}}

    monkeypatch.setattr("src.web_backend.doubao_speech_management.VolcengineOpenApi.post_json", post_json)
    monkeypatch.setattr(
        "src.web_backend.doubao_speech_management.AudioSpeakerCatalog.replace_provider_index",
        lambda _catalog, provider_id, resource_ids, options: indexed.update({
            "provider_id": provider_id,
            "resource_ids": resource_ids,
            "options": options,
        }) or len(options),
    )

    result = DoubaoSpeechManagementDomain(object()).execute("doubao", {
        "operation": "list_speakers",
        "payload": {"ResourceIDs": ["seed-tts-2.0"], "Limit": 1},
    })

    assert result["speaker_option_count"] == 2
    assert indexed == {
        "provider_id": "doubao",
        "resource_ids": ["seed-tts-2.0"],
        "options": [
            {"value": "speaker-1", "label": "Speaker One"},
            {"value": "speaker-2", "label": "speaker-2"},
        ],
    }
    assert requests == [
        {"ResourceIDs": ["seed-tts-2.0"], "Page": 1, "Limit": 1},
        {"ResourceIDs": ["seed-tts-2.0"], "Page": 2, "Limit": 1},
    ]


def test_management_list_speakers_rejects_incomplete_pagination(monkeypatch):
    from src.web_backend.doubao_speech_management import DoubaoSpeechManagementDomain

    monkeypatch.setattr("src.web_backend.doubao_speech_management.ConfigLoader.get_provider_config", lambda *_args: {
        "type": "doubao",
        "apiKey": "speech-key",
        "speechAccessKeyId": "ak-id",
        "speechSecretAccessKey": "secret",
    })
    monkeypatch.setattr("src.web_backend.doubao_speech_management.VolcengineOpenApi.post_json", lambda *_args: {
        "ResponseMetadata": {},
        "Result": {"Speakers": [], "Total": 1},
    })

    with pytest.raises(Exception, match="declared Total=1"):
        DoubaoSpeechManagementDomain(object()).execute("doubao", {
            "operation": "list_speakers",
            "payload": {"ResourceIDs": ["seed-tts-2.0"]},
        })


def test_management_voice_clone_uses_api_key_and_validates_audio(monkeypatch):
    from src.web_backend.doubao_speech_management import DoubaoSpeechManagementDomain

    monkeypatch.setattr("src.web_backend.doubao_speech_management.ConfigLoader.get_provider_config", lambda *_args: {
        "type": "doubao",
        "apiKey": "general-key",
        "xApiKey": "speech-key",
        "baseUrl": "https://openspeech.bytedance.com/api/v3/tts/create",
        "timeoutMs": 60000,
    })
    captured = {}

    def urlopen(request, timeout=None):
        captured["request"] = request
        return _Response({"code": 0, "message": "ok", "speaker_id": "speaker-1"})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = DoubaoSpeechManagementDomain(object()).execute("doubao", {
        "operation": "clone_voice",
        "payload": {"speaker_id": "speaker-1", "audio": {"data": "YWJj", "format": "wav"}},
    })

    assert result["result"]["speaker_id"] == "speaker-1"
    assert captured["request"].get_header("X-api-key") == "speech-key"
    assert captured["request"].full_url.endswith("/api/v3/tts/voice_clone")

    with pytest.raises(Exception, match="audio.data"):
        DoubaoSpeechManagementDomain(object()).execute("doubao", {
            "operation": "clone_voice",
            "payload": {"speaker_id": "speaker-1", "audio": {}},
        })


def test_agent_schema_merges_provider_speaker_suggestions(monkeypatch):
    from nodes.agent_node_schema import build_agent_config_schema

    monkeypatch.setattr("nodes.agent_node_schema.ConfigLoader.get_all_providers", lambda *_args: {
            "doubao": {
                "supportmode": ["audio_generation"],
        },
    })
    monkeypatch.setattr(
        "nodes.agent_node_schema.AudioSpeakerCatalog.get_provider_options",
        lambda *_args: [
            {"value": "speaker-1", "label": "Speaker One"},
            {"value": "speaker-2", "label": "Speaker Two"},
        ],
    )
    monkeypatch.setattr("nodes.agent_node_schema.CapabilityRegistry.discover_payload", lambda *_args: {})
    schema = build_agent_config_schema(
        {
            "audio_speaker": {"type": "combobox", "options": []},
            "tts_speaker": {"type": "combobox", "options": [{"value": "speaker-1", "label": "Existing"}]},
        },
        {"provider_id": "doubao"},
    )

    assert schema["audio_speaker"]["options"][0] == {"value": "speaker-1", "label": "Speaker One"}
    assert [item["value"] for item in schema["tts_speaker"]["options"]] == ["speaker-1", "speaker-2"]
