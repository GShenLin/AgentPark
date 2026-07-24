import base64
import json
from pathlib import Path

import pytest


class _TtsHost:
    def __init__(self, tmp_path, lines):
        self.config = {
            "apiKey": "general-key",
            "xApiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
            "timeoutMs": 60000,
        }
        self.current_memory_path = str(tmp_path / "Agent.json")
        self.lines = lines
        self.request = None
        self.events = []
        self.tool_event_callback = self.events.append

    def _read_provider_config_from_file(self):
        return dict(self.config)

    def _curl_post_sse_raw_lines(self, **kwargs):
        self.request = kwargs
        return iter(self.lines)


def test_tts_http_streams_audio_events_and_saves_final_mp3(tmp_path):
    from src.providers.curl_transport import CurlResponse
    from src.providers.doubao_tts_http import DoubaoTtsHttp

    host = _TtsHost(tmp_path, [
        json.dumps({"code": 0, "data": base64.b64encode(b"a" * 3000).decode("ascii")}),
        json.dumps({"code": 0, "data": base64.b64encode(b"tail").decode("ascii"), "usage": {"text_words": 5}}),
        CurlResponse(body="", status_code=200),
    ])
    result = DoubaoTtsHttp(host).synthesize_tts_http(
        [{"role": "user", "content": "hello"}],
        tts_speaker="speaker-1",
        tts_context_texts='["speak calmly"]',
        tts_additions='{"disable_markdown_filter": true}',
        tts_aigc_watermark=True,
    )

    assert Path(result["audio_path"]).read_bytes() == b"a" * 3000 + b"tail"
    assert result["usage"] == {"text_words": 5}
    assert [event["type"] for event in host.events] == [
        "audio_stream_start",
        "audio_stream_chunk",
        "audio_stream_chunk",
        "audio_stream_chunk",
        "audio_stream_end",
    ]
    assert [event.get("sequence") for event in host.events[1:]] == [0, 1, 2, 3]
    payload = json.loads(host.request["payload_json"])
    params = payload["req_params"]
    assert params["text"] == "hello"
    assert params["speaker"] == "speaker-1"
    assert params["context_texts"] == ["speak calmly"]
    assert json.loads(params["additions"]) == {
        "disable_markdown_filter": True,
        "aigc_watermark": True,
    }
    assert host.request["headers"]["X-Api-Resource-Id"] == "seed-tts-2.0"
    assert host.request["headers"]["X-Api-Key"] == "speech-key"
    assert host.request["yield_all_lines"] is True


def test_tts_http_requires_speaker_and_rejects_provider_error(tmp_path):
    from src.providers.doubao_tts_http import DoubaoTtsHttp

    service = DoubaoTtsHttp(_TtsHost(tmp_path, []))
    with pytest.raises(ValueError, match="tts_speaker is required"):
        service.synthesize_tts_http([{"role": "user", "content": "hello"}])

    host = _TtsHost(tmp_path, [json.dumps({"code": 45000000, "message": "bad request"})])
    with pytest.raises(ValueError, match="45000000"):
        DoubaoTtsHttp(host).synthesize_tts_http(
            [{"role": "user", "content": "hello"}],
            tts_speaker="speaker-1",
        )


def test_live_output_retains_audio_chunks_through_completion():
    from src.web_backend.node_live_output import NodeLiveOutputStore

    store = NodeLiveOutputStore()
    store.publish_event("g", "n", "audio_stream_start", {
        "type": "audio_stream_start",
        "stream_id": "stream-1",
        "mime": "audio/mpeg",
        "format": "mp3",
        "sample_rate": 24000,
    })
    store.publish_event("g", "n", "audio_stream_chunk", {
        "type": "audio_stream_chunk",
        "stream_id": "stream-1",
        "sequence": 0,
        "data": base64.b64encode(b"chunk").decode("ascii"),
    })
    store.publish_completion_event("g", "n", "node_message_done", {"type": "node_message_done"})

    item = store.get("g", "n")
    assert [event["type"] for event in item["media_chunks"]] == ["audio_stream_start", "audio_stream_chunk"]
    assert item["is_streaming"] is False
