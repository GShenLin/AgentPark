from pathlib import Path


class _WsHost:
    def __init__(self, tmp_path):
        self.config = {
            "apiKey": "general-key",
            "xApiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
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


def test_speech_websocket_protocol_round_trip():
    from src.providers.doubao_speech_ws_protocol import AUDIO_ONLY_SERVER, TTS_RESPONSE, WITH_EVENT, SpeechWsMessage

    original = SpeechWsMessage(
        message_type=AUDIO_ONLY_SERVER,
        flag=WITH_EVENT,
        event=TTS_RESPONSE,
        session_id="session-1",
        payload=b"audio",
    )
    parsed = SpeechWsMessage.from_bytes(original.to_bytes())
    assert parsed == original


def test_unidirectional_tts_websocket_streams_and_saves(monkeypatch, tmp_path):
    from src.providers.doubao_speech_ws_protocol import (
        AUDIO_ONLY_SERVER,
        FULL_SERVER_RESPONSE,
        SESSION_FINISHED,
        TTS_RESPONSE,
        WITH_EVENT,
        SpeechWsMessage,
    )
    from src.providers.doubao_tts_websocket import DoubaoTtsWebSocket

    connection = _Connection([
        SpeechWsMessage(
            message_type=AUDIO_ONLY_SERVER,
            flag=WITH_EVENT,
            event=TTS_RESPONSE,
            session_id="server-session",
            payload=b"mp3-audio",
        ).to_bytes(),
        SpeechWsMessage(
            message_type=FULL_SERVER_RESPONSE,
            flag=WITH_EVENT,
            event=SESSION_FINISHED,
            session_id="server-session",
            payload=b"{}",
        ).to_bytes(),
    ])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)
    host = _WsHost(tmp_path)
    result = DoubaoTtsWebSocket(host).synthesize_tts_websocket(
        [{"role": "user", "content": "hello"}],
        operation="tts_ws_unidirectional",
        tts_speaker="speaker-1",
    )

    assert Path(result["audio_path"]).read_bytes() == b"mp3-audio"
    assert connection.closed is True
    assert len(connection.sent) == 1
    assert [event["type"] for event in host.events] == [
        "audio_stream_start", "audio_stream_chunk", "audio_stream_end",
    ]
