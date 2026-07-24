import json

import pytest


class _AsrHost:
    def __init__(self, tmp_path, response):
        self.config = {
            "apiKey": "general-key",
            "xApiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
        self.current_memory_path = str(tmp_path / "Agent.json")
        self.response = response
        self.request = None

    def _read_provider_config_from_file(self):
        return dict(self.config)

    def _curl_post_once_raw(self, **kwargs):
        self.request = kwargs
        return self.response


def test_asr_flash_uses_audio_attachment_and_returns_transcription(tmp_path):
    from src.providers.curl_transport import CurlResponse
    from src.providers.doubao_asr_flash import DoubaoAsrFlash

    audio = tmp_path / "recording.ogg"
    audio.write_bytes(b"ogg-opus")
    response = CurlResponse(
        body=json.dumps({
            "audio_info": {"duration": 2499},
            "result": {"text": "关闭透传。", "utterances": []},
        }, ensure_ascii=False),
        status_code=200,
        headers={"x-api-status-code": "20000000", "x-api-message": "OK"},
    )
    host = _AsrHost(tmp_path, response)
    result = DoubaoAsrFlash(host).recognize_asr_flash(
        [{"role": "user", "content": [{"type": "reference_resource", "kind": "audio", "uri": str(audio)}]}],
        asr_uid="user-1",
    )

    assert result["response"] == "关闭透传。"
    payload = json.loads(host.request["payload_json"])
    assert payload["user"] == {"uid": "user-1"}
    assert payload["audio"]["data"]
    assert payload["request"]["model_name"] == "bigmodel"
    assert host.request["headers"]["X-Api-Sequence"] == "-1"
    assert host.request["headers"]["X-Api-Key"] == "speech-key"


def test_asr_flash_requires_provider_status_header(tmp_path):
    from src.providers.curl_transport import CurlResponse
    from src.providers.doubao_asr_flash import DoubaoAsrFlash

    audio = tmp_path / "input.mp3"
    audio.write_bytes(b"audio")
    host = _AsrHost(tmp_path, CurlResponse(body="{}", status_code=200))
    with pytest.raises(ValueError, match="<missing>"):
        DoubaoAsrFlash(host).recognize_asr_flash(
            [{"role": "user", "content": [{"type": "reference_resource", "kind": "audio", "uri": str(audio)}]}],
        )
