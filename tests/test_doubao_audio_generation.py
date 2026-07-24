import base64
import json
from pathlib import Path

import pytest


class _AudioHost:
    def __init__(self, tmp_path, response):
        self.config = {
            "apiKey": "general-key",
            "xApiKey": "speech-key",
            "baseUrl": "https://openspeech.bytedance.com/api/v3/tts/create",
            "maxRetries": 0,
            "retryDelaySec": 0,
        }
        self.current_memory_path = str(tmp_path / "Agent.json")
        self.response = response
        self.request = None

    def _read_provider_config_from_file(self):
        return dict(self.config)

    def _emit_provider_runtime_notice(self, **_kwargs):
        return None

    def _post_json_with_retry(self, **kwargs):
        self.request = kwargs
        return self.response

    def _curl_get_bytes_with_retry(self, **_kwargs):
        return b"downloaded-audio"


def test_audio_generation_posts_documented_payload_and_saves_audio(tmp_path):
    from src.providers.doubao_audio_generation import DoubaoAudioGeneration

    host = _AudioHost(
        tmp_path,
        {
            "code": 0,
            "message": "success",
            "audio": base64.b64encode(b"mp3-data").decode("ascii"),
            "duration": 1.25,
            "original_duration": 1.5,
        },
    )
    service = DoubaoAudioGeneration(host)
    result = service.generate_audio(
        [{"role": "user", "content": [{"type": "text", "text": "create a sound"}]}],
        audio_model="seed-audio-1.0",
        audio_format="mp3",
        audio_sample_rate="48000",
        audio_speech_rate="0",
        audio_loudness_rate=0,
        audio_pitch_rate=0,
        audio_enable_subtitle="false",
    )

    assert result["response"] == "success"
    assert result["duration"] == 1.25
    assert result["audio_path"].endswith(".mp3")
    assert Path(result["audio_path"]).read_bytes() == b"mp3-data"
    payload = json.loads(host.request["payload_json"])
    assert payload == {
        "model": "seed-audio-1.0",
        "text_prompt": "create a sound",
        "audio_config": {
            "format": "mp3",
            "sample_rate": 48000,
            "speech_rate": 0,
            "loudness_rate": 0,
            "pitch_rate": 0,
            "enable_subtitle": False,
        },
    }
    assert host.request["url"] == "https://openspeech.bytedance.com/api/v3/tts/create"
    assert host.request["headers"]["X-Api-Key"] == "speech-key"
    assert host.request["headers"]["X-Api-Request-Id"]


def test_audio_generation_encodes_local_reference_and_validates_mixing(tmp_path):
    from src.providers.doubao_audio_generation import DoubaoAudioGeneration

    audio = tmp_path / "reference.mp3"
    audio.write_bytes(b"reference")
    host = _AudioHost(tmp_path, {"code": 0, "audio": base64.b64encode(b"result").decode("ascii")})
    service = DoubaoAudioGeneration(host)
    service.generate_audio(
        [{"role": "user", "content": "@音频1 say hello"}],
        audio_references=str(audio),
    )
    payload = json.loads(host.request["payload_json"])
    assert payload["references"] == [{"audio_data": base64.b64encode(b"reference").decode("ascii")}]

    with pytest.raises(ValueError, match="cannot be mixed"):
        service.generate_audio(
            [{"role": "user", "content": "mixed"}],
            audio_references=json.dumps([{"audio_url": "https://example.com/a.mp3"}, {"image_url": "https://example.com/a.png"}]),
        )


def test_audio_generation_rejects_malformed_success_response(tmp_path):
    from src.providers.doubao_audio_generation import DoubaoAudioGeneration

    service = DoubaoAudioGeneration(_AudioHost(tmp_path, {"message": "missing code"}))
    with pytest.raises(ValueError, match="contains neither audio nor url"):
        service.generate_audio([{"role": "user", "content": "sound"}])


def test_audio_generation_accepts_documented_media_payload_without_code(tmp_path):
    from src.providers.doubao_audio_generation import DoubaoAudioGeneration

    host = _AudioHost(
        tmp_path,
        {
            "audio": base64.b64encode(b"mp3-data").decode("ascii"),
            "duration": 0.8,
            "original_duration": 0.8,
            "url": "",
        },
    )

    result = DoubaoAudioGeneration(host).generate_audio(
        [{"role": "user", "content": "sound"}],
    )

    assert Path(result["audio_path"]).read_bytes() == b"mp3-data"
    assert result["duration"] == 0.8


def test_audio_generation_rejects_explicit_nonzero_code_even_with_media(tmp_path):
    from src.providers.doubao_audio_generation import DoubaoAudioGeneration

    service = DoubaoAudioGeneration(
        _AudioHost(
            tmp_path,
            {
                "code": 4001,
                "message": "invalid request",
                "audio": base64.b64encode(b"unexpected").decode("ascii"),
            },
        )
    )
    with pytest.raises(ValueError, match="returned code 4001"):
        service.generate_audio([{"role": "user", "content": "sound"}])


def test_agent_audio_schema_is_support_mode_scoped(monkeypatch):
    from nodes.agent_audio_schema import AUDIO_CONFIG_DEFAULTS
    from nodes.agent_node import Node
    import nodes.agent_node_schema as schema_module

    class DummyLoader:
        def get_all_providers(self):
            return {"seed_audio": {"supportmode": ["audio_generation"]}}

    monkeypatch.setattr(schema_module, "ConfigLoader", DummyLoader)

    schema = Node().get_config_schema({"provider_id": "seed_audio"})
    assert schema["audio_model"]["modes"] == ["audio_generation"]
    assert schema["audio_references"]["type"] == "file_list"
    assert AUDIO_CONFIG_DEFAULTS["audio_references"] == []
    assert "tools" not in schema
    assert "mode" not in schema


def test_audio_input_resource_is_not_gated_by_provider_name_or_leaked_meta():
    from nodes.agent_message_adapter import build_agent_user_content

    content = build_agent_user_content(
        "seed_audio",
        "audio_generation",
        {
            "role": "user",
            "parts": [
                {"type": "meta", "meta": {"support_mode": "audio_generation"}},
                {"type": "text", "text": "match this voice"},
                {
                    "type": "resource",
                    "resource": {
                        "kind": "audio",
                        "uri": "C:/project/reference.mp3",
                        "source": "node_editor",
                    },
                },
            ],
        },
    )

    assert content == [
        {"type": "text", "text": "match this voice"},
        {"type": "reference_resource", "kind": "audio", "uri": "C:/project/reference.mp3"},
    ]


def test_agent_output_message_contains_audio_resource():
    from nodes.agent_message_adapter import build_agent_output_message

    message = build_agent_output_message({"response": "ready", "audio_path": "C:\\tmp\\voice.mp3", "duration": 2.0})
    resources = [part["resource"] for part in message["parts"] if part.get("type") == "resource"]
    assert len(resources) == 1
    assert resources[0]["uri"] == "C:\\tmp\\voice.mp3"
    assert resources[0]["kind"] == "audio"
    assert resources[0]["source"] == "agent"
    assert any(part.get("data") == {"duration": 2.0} for part in message["parts"])
