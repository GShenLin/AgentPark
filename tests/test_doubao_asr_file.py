import json

import pytest


class _AsrFileHost:
    def __init__(self, responses, *, idle_credentials=False):
        self.config = {
            "apiKey": "general-key",
            "xApiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
        if idle_credentials:
            self.config.update({"speechAppId": "app-id", "speechAccessKey": "access-key"})
        self.responses = list(responses)
        self.requests = []

    def _read_provider_config_from_file(self):
        return dict(self.config)

    def _curl_post_once_raw(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)

    def _cancel_source(self):
        return None


def _response(status, body=None, **headers):
    from src.providers.curl_transport import CurlResponse

    return CurlResponse(
        body=json.dumps(body or {}),
        status_code=200,
        headers={"x-api-status-code": status, **headers},
    )


def test_asr_standard_submits_and_polls_to_completion(monkeypatch):
    from src.providers.doubao_asr_file import DoubaoAsrFile

    monkeypatch.setattr("src.providers.doubao_asr_file.sleep_with_cancel", lambda *_args: None)
    host = _AsrFileHost([
        _response("20000000", **{"x-tt-logid": "log-1"}),
        _response("20000001"),
        _response("20000000", {"audio_info": {"duration": 10}, "result": {"text": "done", "utterances": []}}),
    ])
    result = DoubaoAsrFile(host).recognize_asr_file(
        [],
        operation="asr_standard",
        asr_source_audio="https://example.com/input.mp3",
        asr_uid="user-1",
        asr_poll_interval_seconds=0.01,
    )

    assert result["response"] == "done"
    assert len(host.requests) == 3
    assert host.requests[0]["url"].endswith("/api/v3/auc/bigmodel/submit")
    assert host.requests[1]["url"].endswith("/api/v3/auc/bigmodel/query")
    assert host.requests[0]["headers"]["X-Api-Key"] == "speech-key"
    payload = json.loads(host.requests[0]["payload_json"])
    assert payload["audio"]["format"] == "mp3"


def test_asr_idle_requires_legacy_credentials():
    from src.providers.doubao_asr_file import DoubaoAsrFile

    host = _AsrFileHost([])
    with pytest.raises(ValueError, match="speechAppId and speechAccessKey"):
        DoubaoAsrFile(host).recognize_asr_file(
            [],
            operation="asr_idle",
            asr_source_audio="https://example.com/input.wav",
        )


def test_asr_idle_uses_legacy_headers(monkeypatch):
    from src.providers.doubao_asr_file import DoubaoAsrFile

    monkeypatch.setattr("src.providers.doubao_asr_file.sleep_with_cancel", lambda *_args: None)
    host = _AsrFileHost([
        _response("20000000", **{"x-tt-logid": "log-1"}),
        _response("20000000", {"result": {"text": "idle done"}}),
    ], idle_credentials=True)
    DoubaoAsrFile(host).recognize_asr_file(
        [],
        operation="asr_idle",
        asr_source_audio="https://example.com/input.wav",
        asr_poll_interval_seconds=0.01,
    )

    submit_headers = host.requests[0]["headers"]
    query_headers = host.requests[1]["headers"]
    assert submit_headers["X-Api-App-Key"] == "app-id"
    assert submit_headers["X-Api-Access-Key"] == "access-key"
    assert "X-Api-Key" not in submit_headers
    assert query_headers["X-Tt-Logid"] == "log-1"
