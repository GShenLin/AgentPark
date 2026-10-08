"""Bounded, clocked PCM output and microphone resampling for WebRTC bridges."""
import asyncio
from fractions import Fraction

from aiortc import AudioStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame, AudioResampler

from .voice_playback_buffer import PlaybackBuffer


class PcmOutputTrack(AudioStreamTrack):
    rate = 24_000
    samples = 480  # 20 ms

    def __init__(self):
        super().__init__()
        self.buffer = PlaybackBuffer()
        self.timestamp = 0
        self.started: float | None = None

    def append(self, pcm: bytes) -> None:
        if self.readyState != "live":
            raise MediaStreamError
        if len(pcm) % 2:
            raise ValueError("语音供应商返回了不完整的 PCM16 采样。")
        self.buffer.append(pcm)

    def interrupt(self) -> None:
        self.buffer.clear()

    def stop(self) -> None:
        super().stop()
        self.buffer.close()

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        loop = asyncio.get_running_loop()
        if self.started is None:
            self.started = loop.time()
        await asyncio.sleep(max(0, self.started + self.timestamp / self.rate - loop.time()))
        size = self.samples * 2
        if self.readyState != "live":
            raise MediaStreamError
        data = self.buffer.read(size)
        frame = AudioFrame(format="s16", layout="mono", samples=self.samples)
        frame.planes[0].update(data.ljust(size, b"\x00"))
        frame.sample_rate = self.rate
        frame.pts = self.timestamp
        frame.time_base = Fraction(1, self.rate)
        self.timestamp += self.samples
        return frame


class MicrophonePcm:
    def __init__(self):
        self.resampler = AudioResampler(format="s16", layout="mono", rate=16_000)
        self.buffer = bytearray()

    def feed(self, frame: AudioFrame) -> list[bytes]:
        for converted in self.resampler.resample(frame):
            self.buffer.extend(converted.to_ndarray().tobytes())
        result = []
        while len(self.buffer) >= 640:
            result.append(bytes(self.buffer[:640]))
            del self.buffer[:640]
        return result
