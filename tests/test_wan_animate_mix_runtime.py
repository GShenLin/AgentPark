import os
import pytest


def test_wan_animate_mix_runtime_creates_task_polls_and_downloads(tmp_path):
    from src.providers.wan_animate_mix_runtime import WanAnimateMixRuntime

    class DummyHost:
        def __init__(self):
            self.config = {
                "apiKey": "token",
                "baseUrl": "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2video/video-synthesis",
                "model": "wan2.2-animate-mix",
                "maxRetries": 0,
                "retryDelaySec": 0,
                "wanAnimateMixPollIntervalSec": 0.01,
                "wanAnimateMixMaxWaitSec": 5,
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
            return {
                "output": {
                    "task_id": "task-123",
                    "task_status": "PENDING",
                }
            }

        def _get_json_with_retry(self, **kwargs):
            self.get_calls.append(kwargs)
            return {
                "request_id": "req-123",
                "output": {
                    "task_id": "task-123",
                    "task_status": "SUCCEEDED",
                    "results": {
                        "video_url": "https://cdn.example.com/out.mp4",
                    },
                },
                "usage": {
                    "video_duration": 5,
                    "video_ratio": "16:9",
                },
            }

        def _curl_get_bytes_with_retry(self, **kwargs):
            self.download_urls.append(kwargs.get("url"))
            return b"video-bytes"

    host = DummyHost()
    runtime = WanAnimateMixRuntime(host)

    result = runtime.generate_video_change_person(
        image_url="https://cdn.example.com/actor.png",
        video_url="https://cdn.example.com/source.mp4",
        mode="wan-pro",
        watermark=True,
        check_image=False,
        filename_prefix="replace_person",
    )

    assert result["task_id"] == "task-123"
    assert result["request_id"] == "req-123"
    assert result["video_url"] == "https://cdn.example.com/out.mp4"
    assert result["video_duration"] == 5
    assert result["video_ratio"] == "16:9"
    assert os.path.isfile(result["video_path"])
    assert host.download_urls == ["https://cdn.example.com/out.mp4"]

    post_payload = host.post_calls[0]
    assert post_payload["url"] == "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2video/video-synthesis"
    assert post_payload["headers"]["X-DashScope-Async"] == "enable"
    assert '"image_url": "https://cdn.example.com/actor.png"' in post_payload["payload_json"]
    assert '"video_url": "https://cdn.example.com/source.mp4"' in post_payload["payload_json"]
    assert '"mode": "wan-pro"' in post_payload["payload_json"]
    assert '"watermark": true' in post_payload["payload_json"]
    assert '"check_image": false' in post_payload["payload_json"]

    get_payload = host.get_calls[0]
    assert get_payload["url"] == "https://dashscope.aliyuncs.com/api/v1/tasks/task-123"
    assert any("task-123" in str(item.get("content") or "") for item in host.messages)


def test_wan_animate_mix_runtime_rejects_invalid_switch_and_poll_config(tmp_path):
    from src.providers.wan_animate_mix_runtime import WanAnimateMixRuntime

    class DummyHost:
        def __init__(self):
            self.config = {
                "apiKey": "token",
                "baseUrl": "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2video/video-synthesis",
                "model": "wan2.2-animate-mix",
                "watermark": "maybe",
                "wanAnimateMixPollIntervalSec": 0,
            }
            self.current_memory_path = str(tmp_path / "agent" / "agent.md")

        def _post_json_with_retry(self, **_kwargs):
            return {"output": {"task_id": "task-123"}}

    runtime = WanAnimateMixRuntime(DummyHost())

    with pytest.raises(ValueError, match="watermark must be a boolean value"):
        runtime.generate_video_change_person(
            image_url="https://cdn.example.com/actor.png",
            video_url="https://cdn.example.com/source.mp4",
        )

    runtime.config["watermark"] = "true"
    with pytest.raises(ValueError, match="wanAnimateMixPollIntervalSec must be greater than 0"):
        runtime.generate_video_change_person(
            image_url="https://cdn.example.com/actor.png",
            video_url="https://cdn.example.com/source.mp4",
        )
