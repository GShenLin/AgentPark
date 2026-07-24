import gzip
import json
import struct
import wave

import pytest


class _AsrWsHost:
    def __init__(self):
        self.config = {
            "apiKey": "general-key",
            "xApiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
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
        self.recv_count = 0

    def send(self, value):
        self.sent.append(value)

    def recv(self, timeout=None):
        assert timeout
        self.recv_count += 1
        return self.frames.pop(0)

    def close(self):
        self.closed = True


def _response(payload, *, flag=1, sequence=1, error_code=0):
    message_type = 0xF if error_code else 0x9
    encoded = json.dumps(payload).encode("utf-8")
    compression = 0 if error_code else 1
    if compression:
        encoded = gzip.compress(encoded)
    frame = bytes([0x11, (message_type << 4) | flag, 0x10 | compression, 0x00])
    if error_code:
        frame += struct.pack(">I", error_code)
    elif flag in {1, 3}:
        frame += struct.pack(">i", sequence)
    return frame + struct.pack(">I", len(encoded)) + encoded


def _wav(path, *, rate=16000, frames=6400):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\x00\x00" * frames)


def test_asr_ws_protocol_encodes_requests_and_parses_negative_final_response():
    from src.providers.doubao_asr_ws_protocol import audio_request, full_request, parse_response

    request = full_request({"request": {"model_name": "bigmodel"}})
    assert request[:4] == bytes([0x11, 0x10, 0x11, 0x00])
    payload_size = struct.unpack(">I", request[4:8])[0]
    assert json.loads(gzip.decompress(request[8:8 + payload_size]))["request"]["model_name"] == "bigmodel"

    final_audio = audio_request(b"pcm", final=True)
    assert final_audio[:4] == bytes([0x11, 0x22, 0x01, 0x00])
    assert gzip.decompress(final_audio[8:]) == b"pcm"

    parsed = parse_response(_response({"result": {"text": "done"}}, flag=3, sequence=-1))
    assert parsed.message_type == 0x9
    assert parsed.flag == 3
    assert parsed.sequence == -1
    assert parsed.payload["result"]["text"] == "done"


def test_asr_stream_bidirectional_detects_wav_and_emits_text_deltas(monkeypatch, tmp_path):
    from src.providers.doubao_asr_ws_protocol import parse_response
    from src.providers.doubao_asr_websocket import DoubaoAsrWebSocket

    audio_path = tmp_path / "input.wav"
    _wav(audio_path, rate=16000, frames=5000)
    connection = _Connection([
        _response({}),
        _response({"result": {"text": "hello"}}, sequence=2),
        _response({"result": {"text": "hello world"}}, flag=3, sequence=-1),
    ])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr("src.providers.doubao_asr_websocket.sleep_with_cancel", lambda *_args: None)

    host = _AsrWsHost()
    result = DoubaoAsrWebSocket(host).recognize_asr_stream(
        [], asr_source_audio=str(audio_path), asr_stream_chunk_ms=200,
    )

    assert result["response"] == "hello world"
    assert connection.closed is True
    assert connection.recv_count == 3
    assert len(connection.sent) == 3
    request_payload = json.loads(gzip.decompress(connection.sent[0][8:]))
    assert request_payload["audio"] == {"format": "wav", "rate": 16000, "bits": 16, "channel": 1}
    assert [event["delta"] for event in host.events] == ["hello", " world"]


@pytest.mark.parametrize("mode", ["optimized", "stream_input"])
def test_asr_stream_deferred_modes_send_all_audio_before_receiving(monkeypatch, tmp_path, mode):
    from src.providers.doubao_asr_websocket import DoubaoAsrWebSocket

    audio_path = tmp_path / "input.wav"
    _wav(audio_path, frames=5000)
    connection = _Connection([
        _response({}),
        _response({"result": {"text": "final"}}, flag=3, sequence=-1),
    ])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr("src.providers.doubao_asr_websocket.sleep_with_cancel", lambda *_args: None)

    result = DoubaoAsrWebSocket(_AsrWsHost()).recognize_asr_stream(
        [],
        asr_source_audio=str(audio_path),
        asr_stream_endpoint_mode=mode,
        asr_stream_chunk_ms=200,
    )

    assert result["response"] == "final"
    assert connection.recv_count == 2
    assert len(connection.sent) == 3
    assert connection.sent[-1][1] & 0x0F == 2


def test_asr_stream_closes_connection_on_server_error(monkeypatch, tmp_path):
    from src.providers.doubao_asr_websocket import DoubaoAsrWebSocket

    audio_path = tmp_path / "input.wav"
    _wav(audio_path, frames=3200)
    connection = _Connection([_response({"message": "invalid audio"}, error_code=45000151)])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)

    with pytest.raises(ValueError, match="45000151"):
        DoubaoAsrWebSocket(_AsrWsHost()).recognize_asr_stream([], asr_source_audio=str(audio_path))
    assert connection.closed is True


def test_asr_stream_closes_connection_when_cancelled(monkeypatch, tmp_path):
    from src.providers.doubao_asr_websocket import DoubaoAsrWebSocket

    audio_path = tmp_path / "input.wav"
    _wav(audio_path, frames=6400)
    connection = _Connection([_response({})])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(
        "src.providers.doubao_asr_websocket.raise_if_cancel_requested",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("cancelled")),
    )

    with pytest.raises(RuntimeError, match="cancelled"):
        DoubaoAsrWebSocket(_AsrWsHost()).recognize_asr_stream([], asr_source_audio=str(audio_path))
    assert connection.closed is True
