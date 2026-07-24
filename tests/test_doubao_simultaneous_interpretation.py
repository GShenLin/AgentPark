import wave
from pathlib import Path

import pytest


class _SimultransHost:
    def __init__(self, tmp_path, *, api_key=True, legacy=False):
        self.config = {
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
        if api_key:
            self.config.update({"apiKey": "general-key", "xApiKey": "speech-key"})
        if legacy:
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


def _wav(path, *, rate=16000, frames=640):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\x00\x00" * frames)


def _response(event, *, text="", data=b"", status=0, message=""):
    from src.providers.doubao_ast_proto import doubao_ast_pb2 as ast

    response = ast.TranslateResponse(event=event, text=text, data=data)
    if status or message:
        response.response_meta.status_code = status
        response.response_meta.message = message
    return response.SerializeToString()


def test_simultrans_s2t_uses_protobuf_and_emits_translation(monkeypatch, tmp_path):
    from src.providers.doubao_ast_proto import doubao_ast_pb2 as ast
    from src.providers.doubao_simultaneous_interpretation import DoubaoSimultaneousInterpretation

    source = tmp_path / "input.wav"
    _wav(source)
    connection = _Connection([
        _response(ast.SESSION_STARTED),
        _response(ast.SOURCE_SUBTITLE_RESPONSE, text="你好"),
        _response(ast.SOURCE_SUBTITLE_END, text="你好"),
        _response(ast.TRANSLATION_SUBTITLE_RESPONSE, text="hello"),
        _response(ast.TRANSLATION_SUBTITLE_END, text="hello"),
        _response(ast.SESSION_FINISHED),
    ])
    captured = {}

    def connect(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return connection

    monkeypatch.setattr("websockets.sync.client.connect", connect)
    result = DoubaoSimultaneousInterpretation(_SimultransHost(tmp_path)).run_simultaneous_interpretation(
        [], simultrans_source_audio=str(source), simultrans_mode="s2t",
    )

    assert result["source_transcription"] == "你好"
    assert result["translation"] == "hello"
    assert captured["url"].endswith("/api/v4/ast/v2/translate")
    assert captured["additional_headers"]["X-Api-Key"] == "speech-key"
    assert connection.closed is True
    decoded = []
    for frame in connection.sent:
        request = ast.TranslateRequest()
        request.ParseFromString(frame)
        decoded.append(request)
    assert [request.event for request in decoded] == [ast.START_SESSION, ast.TASK_REQUEST, ast.FINISH_SESSION]
    assert decoded[0].request_meta.session_id
    assert decoded[0].request.mode == "s2t"
    assert decoded[0].source_audio.rate == 16000
    assert decoded[1].source_audio.binary_data == b"\x00\x00" * 640


def test_simultrans_s2s_streams_and_saves_ogg(monkeypatch, tmp_path):
    from src.providers.doubao_ast_proto import doubao_ast_pb2 as ast
    from src.providers.doubao_simultaneous_interpretation import DoubaoSimultaneousInterpretation

    source = tmp_path / "input.wav"
    _wav(source)
    connection = _Connection([
        _response(ast.SESSION_STARTED),
        _response(ast.TRANSLATION_SUBTITLE_END, text="hello"),
        _response(ast.TTS_RESPONSE, data=b"OggS-translated"),
        _response(ast.SESSION_FINISHED),
    ])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)
    host = _SimultransHost(tmp_path)
    result = DoubaoSimultaneousInterpretation(host).run_simultaneous_interpretation(
        [],
        simultrans_source_audio=str(source),
        simultrans_mode="s2s",
        simultrans_speaker="zh_female_vv_uranus_bigtts",
    )

    assert Path(result["audio_path"]).read_bytes() == b"OggS-translated"
    assert [event["type"] for event in host.events] == [
        "audio_stream_start", "node_message_delta", "audio_stream_chunk", "audio_stream_end",
    ]


def test_simultrans_rejects_unsupported_language_pair(tmp_path):
    from src.providers.doubao_simultaneous_interpretation import DoubaoSimultaneousInterpretation

    source = tmp_path / "input.wav"
    _wav(source)
    with pytest.raises(ValueError, match="requires source or target"):
        DoubaoSimultaneousInterpretation(_SimultransHost(tmp_path)).run_simultaneous_interpretation(
            [],
            simultrans_source_audio=str(source),
            simultrans_source_language="de",
            simultrans_target_language="fr",
        )


def test_simultrans_uses_legacy_headers_when_api_key_is_absent(monkeypatch, tmp_path):
    from src.providers.doubao_ast_proto import doubao_ast_pb2 as ast
    from src.providers.doubao_simultaneous_interpretation import DoubaoSimultaneousInterpretation

    source = tmp_path / "input.wav"
    _wav(source)
    connection = _Connection([
        _response(ast.SESSION_STARTED),
        _response(ast.TRANSLATION_SUBTITLE_END, text="hello"),
        _response(ast.SESSION_FINISHED),
    ])
    captured = {}

    def connect(_url, **kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr("websockets.sync.client.connect", connect)
    DoubaoSimultaneousInterpretation(_SimultransHost(tmp_path, api_key=False, legacy=True)).run_simultaneous_interpretation(
        [], simultrans_source_audio=str(source),
    )

    assert captured["additional_headers"]["X-Api-App-Id"] == "app-id"
    assert captured["additional_headers"]["X-Api-Access-Key"] == "access-key"
