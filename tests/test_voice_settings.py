import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nodes.agent_node_contract import AGENT_CONFIG_DEFAULTS, AGENT_CONFIG_SCHEMA
from nodes.agent_node_schema import build_agent_config_schema
from src.providers.curl_types import CurlResponse
from src.voice_settings import VOICE_MODEL, node_voice_settings, voice_catalog
from src.web_backend.node_config_service import NodeConfigService
from src.web_backend.node_voice import NodeVoiceApi


def test_node_voice_fields_are_independent_of_main_provider_modes(monkeypatch, tmp_path):
    monkeypatch.setattr("src.audio_speaker_catalog.AudioSpeakerCatalog._default_path",
                        staticmethod(lambda: str(tmp_path / "audio_speaker.json")))
    providers = {
        "text": {"type": "openai", "authMode": "api_key", "supportmode": ["image_generation"]},
        "voice-a": {"type": "openai", "authMode": "codex"},
        "voice-b": {"type": "openai", "authMode": "oauth"},
        "other": {"type": "deepseek", "authMode": "api_key"},
    }
    monkeypatch.setattr("nodes.agent_node_schema.ConfigLoader", lambda: SimpleNamespace(
        get_provider_catalog=lambda: providers))
    for main_provider in ("", "text"):
        schema = build_agent_config_schema(AGENT_CONFIG_SCHEMA, {"provider_id": main_provider})
        assert schema["voice_provider_id"]["options"] == [
            {"value": "", "label": "请选择语音 Provider"},
            {"value": "voice-a", "label": "voice-a"},
            {"value": "voice-b", "label": "voice-b"},
        ]
        assert schema["voice_model"]["type"] == "select"
        assert len(schema["voice_provider_id"]["catalogs"]["voice-a"]["models"][0]["voices"]) == 10
    assert AGENT_CONFIG_DEFAULTS["voice_provider_id"] == ""
    assert AGENT_CONFIG_DEFAULTS["voice_model"] == VOICE_MODEL
    assert AGENT_CONFIG_DEFAULTS["voice"] == "marin"


def test_saved_node_settings_reach_credentials_and_wire_request_independently(tmp_path, monkeypatch):
    store = NodeConfigService()
    configs = {}
    for node, tone, model in (("alice", "marin", VOICE_MODEL), ("bob", "cedar", VOICE_MODEL)):
        path = str(tmp_path / f"{node}.json")
        store.write(path, {"type_id": "agent_node", "provider_id": "text-only", "model": "text-model"})
        store.apply_webui_payload(path, {"fields": {
            "voice_provider_id": node, "voice_model": model, "voice": tone,
        }})
        configs[node] = store.read_strict(path)
        assert configs[node]["provider_id"] == "text-only"
        assert configs[node]["model"] == "text-model"

    loader = Mock()
    loader.get_provider_config.side_effect = lambda provider: {
        "type": "openai", "authMode": "codex", "id": provider,
    }
    monkeypatch.setattr("src.web_backend.node_voice.ConfigLoader", lambda: loader)
    credentials = Mock(side_effect=lambda cfg: SimpleNamespace(
        base_url="https://chatgpt.com/backend-api/codex", headers={"Authorization": cfg["id"]}))
    monkeypatch.setattr("src.providers.openai_realtime_voice.resolve_provider_request_credentials", credentials)
    requests = []
    async def request(*_, **kwargs):
        requests.append(kwargs)
        return CurlResponse("v=0\r\nm=audio 9 test\r\n", 201)
    monkeypatch.setattr("src.providers.openai_realtime_voice.CurlHttpTransport.request_async", request)
    core = SimpleNamespace(
        access_api=SimpleNamespace(message_access_metadata=lambda _: {"_access_client_id": "owner"}),
        node_ops=SimpleNamespace(require_node_visible=Mock(), get_node_instance_config=lambda node, *_, **__: {"node": configs[node]}),
        graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda graph: graph,
            _node_memory_path=lambda *_: str(tmp_path / "memory.md"),
            _node_messages_path=lambda *_: str(tmp_path / "messages.jsonl")),
    )
    (tmp_path / "memory.md").write_text("上次讨论了游戏项目", encoding="utf-8")
    configs["alice"]["system_prompt"] = "使用原节点设定"
    service = NodeVoiceApi(core)
    app = FastAPI()
    app.post("/voice/{node_id}")(service.start)
    client = TestClient(app)
    for node in configs:
        response = client.post(f"/voice/{node}", json={"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n", "protocols": ["openai-realtime-v1"]})
        assert response.status_code == 200
        assert response.json()["model"] == configs[node]["voice_model"]
        body = {"session": json.loads(requests[-1]["body"].decode("utf-8").split('Content-Type: application/json\r\n\r\n', 1)[1].split("\r\n--", 1)[0])}
        assert "上次讨论了游戏项目" in body["session"]["instructions"]
        if node == "alice":
            assert "使用原节点设定" in body["session"]["instructions"]
        assert "每个需要回应" not in body["session"]["instructions"]
        assert body["session"]["model"] == configs[node]["voice_model"]
        assert body["session"]["audio"]["output"]["voice"] == configs[node]["voice"]
        assert requests[-1]["headers"]["Authorization"] == node
    assert [call.args[0] for call in loader.get_provider_config.call_args_list] == ["alice", "bob"]

    configs["alice"].pop("voice_provider_id")
    response = client.post("/voice/alice", json={"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"})
    assert response.status_code == 400
    assert "语音设置" in response.json()["detail"]
    assert len(requests) == 2


@pytest.mark.parametrize("voice", [item["id"] for item in voice_catalog()])
def test_every_listed_voice_is_accepted(voice):
    assert node_voice_settings({"voice": voice}).voice == voice


@pytest.mark.parametrize("payload", [
    {"voice": 1}, {"voice_model": ""},
    {"voice_model": "   "}, {"voice_model": 1}, {"voice_provider_id": []},
])
def test_invalid_node_settings_are_rejected(payload):
    with pytest.raises(ValueError):
        node_voice_settings(payload)
