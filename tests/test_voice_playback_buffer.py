import asyncio

import pytest
from aiortc.mediastreams import MediaStreamError

from src.providers.voice_audio import PcmOutputTrack
from src.providers.voice_playback_buffer import PlaybackBuffer


def test_burst_longer_than_thirty_seconds_spills_and_preserves_every_sample():
    track = PcmOutputTrack()
    try:
        # 90 seconds produced immediately used to disconnect the entire call.
        pcm = bytes(range(256)) * (24_000 * 2 * 90 // 256)
        track.append(pcm)
        assert track.buffer.file._rolled
        assert track.buffer.file.seek(0, 2) <= track.buffer.capacity
        received = bytearray()
        while track.buffer:
            received.extend(track.buffer.read(960))
        assert received == pcm
        assert track.buffer.file.seek(0, 2) == 0
    finally:
        track.stop()
    assert track.buffer.file.closed


def test_ring_reuses_consumed_storage_without_losing_unplayed_audio():
    queue = PlaybackBuffer(memory_bytes=4, capacity_bytes=16)
    try:
        queue.append(b"abcdefghijklm")
        assert queue.read(10) == b"abcdefghij"
        queue.append(b"nopqrstuvw")
        assert queue.file.seek(0, 2) == 16
        assert queue.read(10) == b"klmnopqrst"
        queue.append(b"xyz0123456789")
        assert len(queue) == 16
        with pytest.raises(ValueError, match="容量上限"):
            queue.append(b"!")
        assert queue.read(32) == b"uvwxyz0123456789"
    finally:
        queue.close()


def test_interrupt_discards_disk_backlog_and_playback_resumes_with_new_turn():
    async def run():
        track = PcmOutputTrack()
        try:
            track.append(b"\x00\x10" * (24_000 * 60))
            assert track.buffer.file._rolled
            track.interrupt()
            assert not track.buffer
            assert track.buffer.file.seek(0, 2) == 0
            track.append(b"\x00\x20" * 480)
            frame = await track.recv()
            assert frame.to_ndarray().tobytes() == b"\x00\x20" * 480
            assert frame.pts == 0 and frame.sample_rate == 24_000
            track.stop()
            with pytest.raises(MediaStreamError):
                await track.recv()
        finally:
            track.stop()
        assert track.buffer.file.closed
    asyncio.run(run())
