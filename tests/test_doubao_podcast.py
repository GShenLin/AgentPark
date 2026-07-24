import json
from pathlib import Path

import pytest


class _PodcastHost:
    def __init__(self, tmp_path, *, credentials=True):
        self.config = {
            "apiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
        if credentials:
            self.config.update({"speechAppId": "app-id", "speechAccessKey": "access-key"})
        self.current_memory_path = str(tmp_path / "Agent.json")
        self.events = []
        self.tool_event_callback = self.events.append

    def _read_provider_config_from_file(self):
        return dict(self.config)

    def _cancel_source(self):
        return None


class _Connection:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)

    def recv(self, timeout=None):
        assert timeout
        return self.frames.pop(0)

    def close(self):
        self.closed = True


def _event(event, payload=b"{}", *, audio=False, session_id="session-1"):
    from src.providers.doubao_speech_ws_protocol import (
        AUDIO_ONLY_SERVER,
        FULL_SERVER_RESPONSE,
        WITH_EVENT,
        SpeechWsMessage,
    )

    return SpeechWsMessage(
        message_type=AUDIO_ONLY_SERVER if audio else FULL_SERVER_RESPONSE,
        flag=WITH_EVENT,
        event=event,
        session_id=session_id,
        payload=payload,
    ).to_bytes()


def test_podcast_streams_audio_saves_file_and_closes_connection(monkeypatch, tmp_path):
    from src.providers.doubao_podcast import (
        PODCAST_END,
        PODCAST_ROUND_RESPONSE,
        DoubaoPodcast,
    )
    from src.providers.doubao_speech_ws_protocol import CONNECTION_FINISHED, SESSION_FINISHED, SESSION_STARTED, SpeechWsMessage

    connection = _Connection([
        _event(SESSION_STARTED),
        _event(PODCAST_ROUND_RESPONSE, b"podcast-audio", audio=True),
        _event(PODCAST_END, json.dumps({"meta_info": {"audio_url": "https://example.com/final.mp3"}}).encode()),
        _event(SESSION_FINISHED),
        _event(CONNECTION_FINISHED, session_id=""),
    ])
    captured = {}

    def connect(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return connection

    monkeypatch.setattr("websockets.sync.client.connect", connect)
    host = _PodcastHost(tmp_path)
    result = DoubaoPodcast(host).generate_podcast(
        [{"role": "user", "content": "Discuss agents"}],
        podcast_action=0,
        podcast_format="mp3",
    )

    assert Path(result["audio_path"]).read_bytes() == b"podcast-audio"
    assert result["podcast"]["audio_url"].endswith("final.mp3")
    assert captured["url"].endswith("/api/v3/sami/podcasttts")
    assert captured["additional_headers"]["X-Api-App-Id"] == "app-id"
    assert connection.closed is True
    assert [event["type"] for event in host.events] == [
        "audio_stream_start", "audio_stream_chunk", "audio_stream_end",
    ]
    start = SpeechWsMessage.from_bytes(connection.sent[0])
    payload = json.loads(start.payload)
    assert payload["action"] == 0
    assert payload["input_text"] == "Discuss agents"
    assert payload["input_info"]["return_audio_url"] is True


def test_podcast_action_three_requires_structured_rounds(tmp_path):
    from src.providers.doubao_podcast import DoubaoPodcast

    with pytest.raises(ValueError, match="objects with non-empty"):
        DoubaoPodcast(_PodcastHost(tmp_path)).generate_podcast([], podcast_action=3, podcast_nlp_texts="[]")


def test_podcast_requires_legacy_credentials(tmp_path):
    from src.providers.doubao_podcast import DoubaoPodcast

    with pytest.raises(ValueError, match="speechAppId and speechAccessKey"):
        DoubaoPodcast(_PodcastHost(tmp_path, credentials=False)).generate_podcast(
            [{"role": "user", "content": "topic"}],
        )
