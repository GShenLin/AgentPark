"""Bounded PCM FIFO that spills to a temporary ring file for fast TTS producers.

The speech websocket must keep reading control/interrupt events even while TTS
outruns realtime playback. Disk spooling bounds RAM without blocking that reader.
"""
from tempfile import SpooledTemporaryFile


class PlaybackBuffer:
    def __init__(self, *, memory_bytes: int = 256 * 1024, capacity_bytes: int = 64 * 1024 * 1024):
        if not 0 < memory_bytes <= capacity_bytes:
            raise ValueError("播放缓冲的内存和总容量配置无效。")
        self.capacity = capacity_bytes
        self.memory_limit = memory_bytes
        self.file = SpooledTemporaryFile(max_size=memory_bytes, mode="w+b")
        self.read_position = 0
        self.write_position = 0
        self.pending = 0

    def __len__(self) -> int:
        return self.pending

    def append(self, data: bytes) -> None:
        if len(data) > self.capacity - self.pending:
            raise ValueError(f"语音临时播放队列已达到 {self.capacity // (1024 * 1024)} MiB 容量上限，已停止通话。")
        # Spill before writing a large packet, avoiding a transient RAM spike.
        if self.write_position + len(data) > self.memory_limit:
            self.file.rollover()
        view = memoryview(data)
        while view:
            count = min(len(view), self.capacity - self.write_position)
            self.file.seek(self.write_position)
            written = self.file.write(view[:count])
            if written != count:
                raise OSError("语音临时播放文件未完整写入。")
            self.write_position = (self.write_position + count) % self.capacity
            self.pending += count
            view = view[count:]

    def read(self, size: int) -> bytes:
        remaining = min(size, self.pending)
        if remaining == 0:
            return b""
        parts = []
        while remaining:
            count = min(remaining, self.capacity - self.read_position)
            self.file.seek(self.read_position)
            part = self.file.read(count)
            if len(part) != count:
                raise OSError("语音临时播放文件读取不完整。")
            parts.append(part)
            self.read_position = (self.read_position + count) % self.capacity
            self.pending -= count
            remaining -= count
        if self.pending == 0:
            self.clear()
        return b"".join(parts)

    def clear(self) -> None:
        self.file.seek(0)
        self.file.truncate(0)
        self.pending = self.read_position = self.write_position = 0

    def close(self) -> None:
        self.file.close()
        self.pending = 0
