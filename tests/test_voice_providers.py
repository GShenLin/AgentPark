import asyncio
import base64
import json

import pytest
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from nodes.agent_voice_schema import materialize_voice_schema
from src.providers.openai_realtime_voice import OpenAIRealtimeVoiceProvider
from src.providers.doubao_voice import DoubaoVoiceProvider, REALTIME_VOICES, SC2_VOICES
from src.providers.voice_provider import VoiceTaskUpdate
from src.providers.voice_registry import provider_voice_catalog, voice_provider
from src.voice_settings import VoiceSettings

CONFIG = {"type": "doubao", "baseUrl": "https://openspeech.bytedance.com/api/v3/tts/create", "xApiKey": "secret"}
SETTINGS = VoiceSettings(provider_id="speech", model="1.2.6.1", voice=REALTIME_VOICES[0].id)


def test_registry_catalogs_and_cross_vendor_validation():
    assert isinstance(voice_provider(CONFIG), DoubaoVoiceProvider)
    assert isinstance(voice_provider({"type": "openai", "authMode": "codex"}), OpenAIRealtimeVoiceProvider)
    assert provider_voice_catalog({"type": "doubao", "baseUrl": "https://ark.cn-beijing.volces.com/api/v3"}) is None
    with pytest.raises(ValueError, match="尚无实时语音"):
        voice_provider({"type": "openai", "authMode": "api_key"})
    for model in DoubaoVoiceProvider.models:
        for speaker in model.voices:
            DoubaoVoiceProvider.validate(VoiceSettings(model=model.id, voice=speaker.id))
    with pytest.raises(ValueError, match="不支持音色"):
        DoubaoVoiceProvider.validate(SETTINGS.model_copy(update={"voice": "cove"}))
    with pytest.raises(ValueError, match="不支持语音模型"):
        OpenAIRealtimeVoiceProvider.validate(SETTINGS)
    schema = materialize_voice_schema({}, {"speech": CONFIG})
    catalogs = schema["voice_provider_id"]["catalogs"]
    assert len(catalogs["speech"]["models"]) == 1
    assert "secret" not in json.dumps(schema)
    assert "xApiKey" not in json.dumps(schema)


class Upstream:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.sent = []
        self.closed = asyncio.Event()
        self.audio_received = asyncio.Event()

    async def recv(self):
        return await self.queue.get()

    async def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        if message["type"] == "input_audio_buffer.append":
            assert len(base64.b64decode(message["audio"])) == 640
            self.audio_received.set()
        elif message["type"] in {"session.create", "session.close"}:
            event = {"session.create": "session.created", "session.close": "session.closed"}[message["type"]]
            await self.queue.put(json.dumps({"type": event}))

    async def event(self, kind, **payload):
        await self.queue.put(json.dumps({"type": kind, **payload}))

    async def close(self):
        self.closed.set()


def test_real_webrtc_bridge_audio_captions_and_hangup(monkeypatch):
    async def exercise():
        upstream = Upstream()

        async def connect(url, **kwargs):
            assert url == "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
            assert kwargs["additional_headers"]["X-Api-Key"] == "secret"
            return upstream

        monkeypatch.setattr("src.providers.doubao_voice_session.connect", connect)
        browser = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        browser.addTrack(AudioStreamTrack())
        channel = browser.createDataChannel("oai-events")
        messages = asyncio.Queue()
        tracks = asyncio.Queue()
        channel.on("message", lambda raw: messages.put_nowait(json.loads(raw)))
        browser.on("track", tracks.put_nowait)
        call = None
        try:
            await browser.setLocalDescription(await browser.createOffer())
            call = await DoubaoVoiceProvider().create_call(CONFIG, browser.localDescription.sdp, "节点背景", SETTINGS)
            assert call.protocol == "agentpark-voice-v4"
            await browser.setRemoteDescription(RTCSessionDescription(sdp=call.sdp, type="answer"))
            async with asyncio.timeout(12):
                assert await messages.get() == {"type": "ready"}
                await upstream.audio_received.wait()
                output = await tracks.get()
                await upstream.event("conversation.item.input_audio_transcription.started", item_id="q1")
                assert await messages.get() == {"type": "interrupted"}
                await upstream.event("conversation.item.input_audio_transcription.completed", item_id="q1", text="测试")
                assert (await messages.get())["text"] == "测试"
                await upstream.event("response.function_call_arguments.done", items=[{
                    "call_id": "call1", "name": "delegate_to_node", "arguments": '{"text":"读取文件"}'}])
                assert (await messages.get())["type"] == "delegation"
                await call.session.deliver_update("call1", VoiceTaskUpdate(task_id="task1", status="completed", text="节点结果"))
                await upstream.event("response.output_text.done", response_id="r1", text="节点结果")
                assert (await messages.get())["text"] == "节点结果"
                await upstream.event("response.output_audio.started", response_id="r1")
                await upstream.event("response.output_audio.delta",
                                     delta=base64.b64encode(b"\x00\x10" * 24000).decode())
                while True:
                    received = await output.recv()
                    if abs(received.to_ndarray()).max() > 50:
                        break
                await upstream.event("conversation.item.input_audio_transcription.started", item_id="q2")
                await asyncio.sleep(.05)
                assert not call.session.audio.buffer
                channel.send('{"type":"session.close"}')
                await upstream.closed.wait()
                await call.session.aclose()
                assert call.session.pc.connectionState == "closed"
                assert not call.session.tasks
            start = next(item for item in upstream.sent if item["type"] == "session.create")
            assert start["session"]["audio"]["output"]["format"] == {"type": "pcm_s16le", "rate": 24000}
            assert start["session"]["model"] == "1.2.6.1"
            assert start["session"]["audio"]["output"]["voice"] == SETTINGS.voice
            assert "节点背景" in start["session"]["instructions"]
            assert start["session"]["tools"][0]["name"] == "delegate_to_node"
            assert upstream.sent[-1]["type"] == "session.close"
        finally:
            if call:
                await call.session.aclose()
            await browser.close()
    asyncio.run(exercise())


def test_failed_handshake_closes_media_and_redacts_key(monkeypatch):
    async def exercise():
        from src.providers.doubao_voice_session import DoubaoVoiceSession
        session = DoubaoVoiceSession(CONFIG, SETTINGS, "", ())
        async def invalid(_):
            raise ValueError("rejected secret")
        monkeypatch.setattr(session.pc, "setRemoteDescription", invalid)
        try:
            with pytest.raises(ValueError, match="rejected \\[redacted\\]"):
                await session.start("invalid")
        finally:
            await session.aclose()
        assert session.pc.connectionState == "closed"
        assert session.audio.readyState == "ended"
    asyncio.run(exercise())
