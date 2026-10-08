"""Owned WebRTC <-> Doubao WebSocket session; no credentials reach the browser."""
import asyncio
import base64
import json
import logging

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .doubao_speech_auth import require_doubao_x_api_key
from .doubao_node_voice import DoubaoNodeVoice, NODE_TOOL
from .voice_instructions import dialogue_instructions
from .voice_audio import MicrophonePcm, PcmOutputTrack
from .voice_provider import VoiceDelivery, VoiceSession, VoiceTaskUpdate

logger = logging.getLogger(__name__)
ENDPOINT = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"


class DoubaoVoiceSession(VoiceSession):
    def __init__(self, config, settings, context, ice_servers):
        self.key = require_doubao_x_api_key(config, "豆包实时语音")
        self.settings = settings
        self.loop = asyncio.get_running_loop()
        self.pc = RTCPeerConnection(RTCConfiguration(
            iceServers=[RTCIceServer(**server) for server in ice_servers]))
        self.audio = PcmOutputTrack()
        self.dialogue = DoubaoNodeVoice(self._send_event, self._emit, self.audio)
        self.context = context
        self.ws = None
        self.channel = None
        self.ready = asyncio.Event()
        self.session_started = False
        self.tasks: set[asyncio.Task] = set()
        self.closing: asyncio.Task | None = None
        self.deadline = None
        self.connect_deadline = None
        self.pc.addTrack(self.audio)

        @self.pc.on("track")
        def on_track(track):
            if track.kind != "audio":
                self._fail("语音通话收到不支持的媒体轨道。")
                return
            self._spawn(self._microphone(track))

        @self.pc.on("connectionstatechange")
        def state_changed():
            if self.pc.connectionState in {"failed", "closed"}:
                self.close()

        @self.pc.on("datachannel")
        def on_channel(channel):
            if self.channel is not None or channel.label != "oai-events" or not channel.ordered:
                channel.close()
                self._fail("语音数据通道不符合通话协议。")
                return
            self.channel = channel

            @channel.on("message")
            def on_message(raw):
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict) or event.get("type") != "session.close":
                        raise ValueError("豆包语音通话不支持此客户端事件。")
                    self.close()
                except (ValueError, TypeError) as exc:
                    self._fail(str(exc))

            @channel.on("close")
            def on_close():
                self.close()

            self.connect_deadline.cancel()
            self._emit({"type": "ready"})

    def _spawn(self, coroutine):
        task = self.loop.create_task(self._run(coroutine))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _run(self, coroutine):
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(self._safe_error(exc))

    def _safe_error(self, exc):
        return (str(exc) or type(exc).__name__).replace(self.key, "[redacted]")[:1000]

    def _emit(self, event):
        if self.channel is not None and self.channel.readyState == "open":
            self.channel.send(json.dumps(event, ensure_ascii=False))

    def _fail(self, message):
        if self.closing is not None:
            return
        logger.warning("Doubao voice: %s", message)
        self._emit({"type": "error", "text": message})
        self.close()

    async def _receive(self):
        raw = await self.ws.recv()
        if not isinstance(raw, str):
            raise ValueError("豆包实时语音返回了非 JSON 文本消息。")
        message = json.loads(raw)
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise ValueError("豆包实时语音返回了无效事件。")
        if message["type"] == "error":
            raise ValueError("豆包语音错误：" + json.dumps(message, ensure_ascii=False))
        return message

    async def _expect(self, event):
        async with asyncio.timeout(12):
            message = await self._receive()
            if message["type"] != event:
                raise ValueError(f"豆包语音握手返回事件 {message['type']}，预期 {event}。")

    async def start(self, sdp):
        payload = {"type": "session.create", "session": {
            "model": self.settings.model,
            "instructions": dialogue_instructions(self.context, "delegate_to_node"),
            "audio": {"input": {"format": {"type": "pcm", "rate": 16000}},
                      "output": {"format": {"type": "pcm_s16le", "rate": 24000}, "voice": self.settings.voice}},
            "tools": [NODE_TOOL]}, "extension": {"asr": {}, "tts": {}, "dialog": {}}}
        try:
            await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
            self.ws = await connect(ENDPOINT, additional_headers={"X-Api-Key": self.key},
                                    open_timeout=15, close_timeout=3, max_size=8 * 1024 * 1024)
            await self._send_event(payload)
            await self._expect("session.created")
            self.session_started = True
            await self.pc.setLocalDescription(await self.pc.createAnswer())
            self.ready.set()
            self._spawn(self._upstream())
            self._spawn(self._notifications())
            self.connect_deadline = self.loop.call_later(30, self._fail, "等待浏览器语音连接超时。")
            self.deadline = self.loop.call_later(3600, self._fail, "本次语音通话已达到一小时上限。")
            return self.pc.localDescription.sdp
        except Exception as exc:
            raise ValueError("创建豆包语音通话失败：" + self._safe_error(exc)) from None

    async def _microphone(self, track):
        await self.ready.wait()
        converter = MicrophonePcm()
        try:
            while True:
                frame = await track.recv()
                for pcm in converter.feed(frame):
                    await self._send_event({"type": "input_audio_buffer.append",
                                            "audio": base64.b64encode(pcm).decode("ascii")})
        except MediaStreamError:
            self.close()

    async def _upstream(self):
        while True:
            message = await self._receive()
            if message["type"] == "session.closed":
                self._emit({"type": "closed"})
                self.close()
                return
            self.dialogue.receive(message)

    async def _notifications(self):
        while True:
            await self.dialogue.flush_notifications()
            await asyncio.sleep(.05)

    async def _send_event(self, event: dict):
        await self.ws.send(json.dumps(event, ensure_ascii=False))

    async def deliver_update(self, delegation_id: str, result: VoiceTaskUpdate) -> VoiceDelivery:
        if self.closing is not None:
            raise ValueError("语音会话已经结束，结果仍保留在节点记录中。")
        try:
            return await self.dialogue.deliver_update(delegation_id, result)
        except Exception as exc:
            message = "回传节点工具结果失败：" + self._safe_error(exc)
            self._fail(message)
            raise ValueError(message) from None

    def close(self):
        self.loop.call_soon_threadsafe(self._begin_close)

    def _begin_close(self):
        if self.closing is None:
            self.closing = self.loop.create_task(self._close())
            self.closing.add_done_callback(self._closed)

    def _closed(self, task):
        if not task.cancelled() and task.exception() is not None:
            logger.error("Doubao voice teardown failed: %s", self._safe_error(task.exception()))

    async def aclose(self):
        self._begin_close()
        await asyncio.shield(self.closing)

    async def _close(self):
        for timer in (self.deadline, self.connect_deadline):
            if timer is not None:
                timer.cancel()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.audio.stop()
        try:
            if self.ws is not None:
                try:
                    async with asyncio.timeout(3):
                        if self.session_started:
                            await self._send_event({"type": "session.close"})
                            while (await self._receive())["type"] != "session.closed":
                                pass
                except (ConnectionClosed, TimeoutError, ValueError) as exc:
                    logger.warning("Doubao voice finish acknowledgement: %s", self._safe_error(exc))
                finally:
                    await self.ws.close()
        finally:
            await self.pc.close()
