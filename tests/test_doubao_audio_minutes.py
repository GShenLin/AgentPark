import json

import pytest


class _MinutesHost:
    def __init__(self, responses, *, credentials=True):
        self.config = {
            "apiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
        if credentials:
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


def _response(body, status="20000000"):
    from src.providers.curl_transport import CurlResponse

    return CurlResponse(json.dumps(body), 200, {"x-api-status-code": status})


def test_audio_minutes_submits_and_polls_to_success(monkeypatch):
    from src.providers.doubao_audio_minutes import DoubaoAudioMinutes

    monkeypatch.setattr("src.providers.doubao_audio_minutes.sleep_with_cancel", lambda *_args: None)
    host = _MinutesHost([
        _response({"Data": {"TaskID": "task-1"}}),
        _response({"Data": {"TaskID": "task-1", "Status": "running"}}),
        _response({"Data": {"TaskID": "task-1", "Status": "success", "Result": {
            "AudioTranscriptionFile": "https://example.com/transcription.json",
            "SummarizationFile": "https://example.com/summary.json",
        }}}),
    ])

    result = DoubaoAudioMinutes(host).generate_minutes(
        [],
        minutes_source_url="https://example.com/meeting.wav",
        minutes_poll_interval_seconds=0.01,
    )

    assert result["task_id"] == "task-1"
    assert result["minutes"]["SummarizationFile"].endswith("summary.json")
    assert len(host.requests) == 3
    assert host.requests[0]["url"].endswith("/api/v3/auc/lark/submit")
    assert host.requests[1]["url"].endswith("/api/v3/auc/lark/query")
    assert host.requests[0]["headers"]["X-Api-App-Key"] == "app-id"
    assert host.requests[1]["headers"]["X-Api-Request-Id"] == "task-1"
    payload = json.loads(host.requests[0]["payload_json"])
    assert payload["Params"]["AudioTranscriptionEnable"] is True
    assert payload["Params"]["SummarizationParams"] == {"Types": ["summary"]}


def test_audio_minutes_requires_legacy_credentials():
    from src.providers.doubao_audio_minutes import DoubaoAudioMinutes

    with pytest.raises(ValueError, match="speechAppId and speechAccessKey"):
        DoubaoAudioMinutes(_MinutesHost([], credentials=False)).generate_minutes(
            [], minutes_source_url="https://example.com/meeting.wav",
        )


def test_audio_minutes_rejects_empty_feature_set():
    from src.providers.doubao_audio_minutes import DoubaoAudioMinutes

    with pytest.raises(ValueError, match="at least one additional"):
        DoubaoAudioMinutes(_MinutesHost([])).generate_minutes(
            [],
            minutes_source_url="https://example.com/meeting.wav",
            minutes_all_activate=False,
            minutes_summarization_enabled=False,
            minutes_chapter_enabled=False,
        )
