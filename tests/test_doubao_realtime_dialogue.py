import json
import wave
from pathlib import Path

import pytest


class _RealtimeHost:
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


def _event(event, payload=b"{}", *, audio=False, session_id="session-1", connect_id="connect-1"):
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
        connect_id=connect_id,
        payload=payload,
    ).to_bytes()


def _wav(path, *, rate=16000, width=2, channels=1, frames=640):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(b"\x00" * frames * width * channels)


def test_realtime_audio_file_streams_pcm_and_saves_response_audio(monkeypatch, tmp_path):
    from src.providers.doubao_realtime_dialogue import ASR_RESPONSE, CHAT_RESPONSE, DoubaoRealtimeDialogue
    from src.providers.doubao_speech_ws_protocol import (
        AUDIO_ONLY_CLIENT,
        CONNECTION_FINISHED,
        CONNECTION_STARTED,
        FINISH_CONNECTION,
        FINISH_SESSION,
        SESSION_FINISHED,
        SESSION_STARTED,
        TTS_ENDED,
        TTS_RESPONSE,
        SpeechWsMessage,
    )

    source = tmp_path / "input.wav"
    _wav(source)
    connection = _Connection([
        _event(CONNECTION_STARTED, connect_id="server-connect"),
        _event(SESSION_STARTED),
        _event(ASR_RESPONSE, json.dumps({"results": [{"text": "question", "is_interim": False}]}).encode()),
        _event(CHAT_RESPONSE, json.dumps({"content": "answer"}).encode()),
        _event(TTS_RESPONSE, b"OggS-audio", audio=True),
        _event(TTS_ENDED),
        _event(SESSION_FINISHED),
        _event(CONNECTION_FINISHED, session_id="", connect_id="server-connect"),
    ])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr("src.providers.doubao_realtime_dialogue.sleep_with_cancel", lambda *_args: None)
    host = _RealtimeHost(tmp_path)

    result = DoubaoRealtimeDialogue(host).run_realtime_dialogue(
        [], realtime_source_audio=str(source), realtime_input_mode="audio_file",
    )

    assert result["response"] == "answer"
    assert result["transcription"] == "question"
    assert Path(result["audio_path"]).read_bytes() == b"OggS-audio"
    assert connection.closed is True
    decoded = [SpeechWsMessage.from_bytes(frame) for frame in connection.sent]
    audio_requests = [message for message in decoded if message.message_type == AUDIO_ONLY_CLIENT]
    assert len(audio_requests) == 2
    assert b"".join(message.payload for message in audio_requests) == b"\x00" * 1280
    assert decoded[-2].event == FINISH_SESSION
    assert decoded[-1].event == FINISH_CONNECTION
    assert [event["type"] for event in host.events] == [
        "audio_stream_start", "node_message_delta", "audio_stream_chunk", "audio_stream_end",
    ]


def test_realtime_text_mode_uses_chat_text_query(monkeypatch, tmp_path):
    from src.providers.doubao_realtime_dialogue import CHAT_RESPONSE, CHAT_TEXT_QUERY, DoubaoRealtimeDialogue
    from src.providers.doubao_speech_ws_protocol import (
        CONNECTION_FINISHED,
        CONNECTION_STARTED,
        SESSION_FINISHED,
        SESSION_STARTED,
        TTS_ENDED,
        TTS_RESPONSE,
        SpeechWsMessage,
    )

    connection = _Connection([
        _event(CONNECTION_STARTED),
        _event(SESSION_STARTED),
        _event(CHAT_RESPONSE, json.dumps({"content": "text answer"}).encode()),
        _event(TTS_RESPONSE, b"audio", audio=True),
        _event(TTS_ENDED),
        _event(SESSION_FINISHED),
        _event(CONNECTION_FINISHED, session_id=""),
    ])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)

    DoubaoRealtimeDialogue(_RealtimeHost(tmp_path)).run_realtime_dialogue(
        [{"role": "user", "content": "hello"}], realtime_input_mode="text",
    )

    decoded = [SpeechWsMessage.from_bytes(frame) for frame in connection.sent]
    query = next(message for message in decoded if message.event == CHAT_TEXT_QUERY)
    assert json.loads(query.payload) == {"content": "hello"}


def test_realtime_rejects_non_16khz_wav(tmp_path):
    from src.providers.doubao_realtime_dialogue import DoubaoRealtimeDialogue

    source = tmp_path / "input.wav"
    _wav(source, rate=48000)
    with pytest.raises(ValueError, match="16 kHz"):
        DoubaoRealtimeDialogue(_RealtimeHost(tmp_path)).run_realtime_dialogue(
            [], realtime_source_audio=str(source),
        )


def test_realtime_requires_legacy_credentials(tmp_path):
    from src.providers.doubao_realtime_dialogue import DoubaoRealtimeDialogue

    with pytest.raises(ValueError, match="speechAppId and speechAccessKey"):
        DoubaoRealtimeDialogue(_RealtimeHost(tmp_path, credentials=False)).run_realtime_dialogue(
            [{"role": "user", "content": "hello"}], realtime_input_mode="text",
        )
