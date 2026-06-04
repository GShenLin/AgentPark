import os
import pytest


def test_doubao_video_generation_creates_task_polls_and_downloads(tmp_path):
    from src.providers.doubao_video_generation import DoubaoVideoGeneration

    class DummyHost:
        def __init__(self):
            self.config = {
                "apiKey": "token",
                "baseUrl": "https://ark.cn-beijing.volces.com/api/v3",
                "model": "doubao-seedance-2-0-260128",
                "maxRetries": 0,
                "retryDelaySec": 0,
                "videoPollIntervalSec": 0.01,
                "videoMaxWaitSec": 5,
            }
            self.current_memory_path = str(tmp_path / "agent" / "agent.md")
            self.messages = []
            self.post_calls = []
            self.get_calls = []
            self.download_urls = []

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def _post_json_with_retry(self, **kwargs):
            self.post_calls.append(kwargs)
            return {"id": "task-123"}

        def _get_json_with_retry(self, **kwargs):
            self.get_calls.append(kwargs)
            return {
                "id": "task-123",
                "status": "succeeded",
                "model": "doubao-seedance-2-0-260128",
                "content": {
                    "video_url": "https://cdn.example.com/output/demo-video.mp4",
                    "last_frame_url": "https://cdn.example.com/output/demo-last-frame.png",
                },
            }

        def _curl_get_bytes_with_retry(self, **kwargs):
            self.download_urls.append(kwargs.get("url"))
            return b"video-bytes"

    host = DummyHost()
    runtime = DoubaoVideoGeneration(host)

    result = runtime.generate_video(
        content=[{"type": "text", "text": "generate a demo video"}],
        resolution="720p",
        ratio="16:9",
        duration=5,
        seed=-1,
        camera_fixed=False,
        watermark=True,
        generate_audio=False,
        return_last_frame=True,
        callback_url="https://callback.example.com/video",
        service_tier="default",
        execution_expires_after=7200,
        safety_identifier="user-hash",
    )

    assert result["task_id"] == "task-123"
    assert os.path.isfile(result["video_path"])
    assert result["last_frame_url"] == "https://cdn.example.com/output/demo-last-frame.png"
    assert host.download_urls == ["https://cdn.example.com/output/demo-video.mp4"]

    post_payload = host.post_calls[0]
    assert post_payload["url"] == "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
    assert '"resolution": "720p"' in post_payload["payload_json"]
    assert '"ratio": "16:9"' in post_payload["payload_json"]
    assert '"duration": 5' in post_payload["payload_json"]
    assert '"seed": -1' in post_payload["payload_json"]
    assert '"camera_fixed": false' in post_payload["payload_json"]
    assert '"generate_audio": false' in post_payload["payload_json"]
    assert '"return_last_frame": true' in post_payload["payload_json"]
    assert '"callback_url": "https://callback.example.com/video"' in post_payload["payload_json"]
    assert '"service_tier": "default"' in post_payload["payload_json"]
    assert '"execution_expires_after": 7200' in post_payload["payload_json"]
    assert '"safety_identifier": "user-hash"' in post_payload["payload_json"]

    get_payload = host.get_calls[0]
    assert get_payload["url"] == "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/task-123"
    assert any("saved_files" in str(msg.get("content") or "") for msg in host.messages)


def test_doubao_video_generation_validates_seed_and_expiration_ranges(tmp_path):
    from src.providers.doubao_video_generation import DoubaoVideoGeneration

    class DummyHost:
        def __init__(self):
            self.config = {
                "apiKey": "token",
                "baseUrl": "https://ark.cn-beijing.volces.com/api/v3",
                "model": "doubao-seedance-2-0-260128",
            }
            self.current_memory_path = str(tmp_path / "agent" / "agent.md")

        def Message(self, role, content, persist=True, **kwargs):
            raise AssertionError("Message should not be called")

    runtime = DoubaoVideoGeneration(DummyHost())

    with pytest.raises(ValueError, match="seed must be <= 4294967295"):
        runtime._resolve_create_payload(
            model="doubao-seedance-2-0-260128",
            content=[{"type": "text", "text": "demo"}],
            seed=4294967296,
        )

    with pytest.raises(ValueError, match="execution_expires_after must be >= 3600"):
        runtime._resolve_create_payload(
            model="doubao-seedance-2-0-260128",
            content=[{"type": "text", "text": "demo"}],
            execution_expires_after=3599,
        )
