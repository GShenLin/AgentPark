def test_video_generation_node_calls_provider_and_returns_video(monkeypatch, tmp_path):
    import nodes.video_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_video(self, content, **kwargs):
            self.calls.append({"content": content, **kwargs})
            return {
                "response": "done",
                "video_path": str(tmp_path / "out.mp4"),
                "last_frame_url": "https://cdn.example.com/out-last.png",
                "task_id": "task-1",
                "video_url": "https://cdn.example.com/out.mp4",
                "status": "success",
            }

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    result = node.on_input(
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "做一个广告视频"},
                {"type": "resource", "resource": {"kind": "image", "uri": "https://cdn.example.com/ref.png"}},
            ],
        },
        {
            "graph_id": "g1",
            "node_instance_id": "video1",
            "provider_id": "doubao-seedance-2-0-260128",
            "resolution": "720p",
            "ratio": "16:9",
            "duration": "5",
            "seed": "-1",
            "camera_fixed": False,
            "generate_audio": "true",
            "watermark": "false",
            "return_last_frame": True,
            "callback_url": "https://callback.example.com/video",
            "service_tier": "default",
            "execution_expires_after": "7200",
            "safety_identifier": "user-hash",
            "web_search": "enabled",
        },
    )

    assert dummy_agent.calls
    call = dummy_agent.calls[0]
    assert call["resolution"] == "720p"
    assert call["ratio"] == "16:9"
    assert call["duration"] == "5"
    assert call["seed"] == "-1"
    assert call["camera_fixed"] is False
    assert call["return_last_frame"] is True
    assert call["callback_url"] == "https://callback.example.com/video"
    assert call["service_tier"] == "default"
    assert call["execution_expires_after"] == "7200"
    assert call["safety_identifier"] == "user-hash"
    assert call["tools"] == [{"type": "web_search"}]
    assert call["content"][0] == {"type": "text", "text": "做一个广告视频"}
    assert call["content"][1]["type"] == "image_url"

    payload = result["routes"][0]["payload"]
    parts = payload["parts"]
    assert any(part.get("type") == "resource" and (part.get("resource") or {}).get("kind") == "video" for part in parts)
    assert any(
        part.get("type") == "resource"
        and (part.get("resource") or {}).get("kind") == "image"
        and (part.get("resource") or {}).get("uri") == "https://cdn.example.com/out-last.png"
        for part in parts
    )


def test_video_generation_node_accepts_local_image_without_public_base_url(monkeypatch, tmp_path):
    import nodes.video_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_video(self, content, **kwargs):
            self.calls.append({"content": content, **kwargs})
            return {"response": "ok", "video_path": str(tmp_path / "out.mp4")}

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    image_path = tmp_path / "local.png"
    image_path.write_bytes(b"png")

    node = node_module.Node()
    result = node.on_input(
        {
            "role": "user",
            "parts": [
                {"type": "resource", "resource": {"kind": "image", "uri": str(image_path)}},
            ],
        },
        {
            "graph_id": "g1",
            "node_instance_id": "video2",
            "provider_id": "doubao-seedance-2-0-260128",
        },
    )

    assert result["display"].startswith("ok")
    assert str(tmp_path / "out.mp4") in result["display"]
    assert dummy_agent.calls[0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_video_generation_node_accepts_first_and_last_frame_paths_from_config(monkeypatch, tmp_path):
    import nodes.video_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_video(self, content, **kwargs):
            self.calls.append({"content": content, **kwargs})
            return {"response": "ok", "video_path": str(tmp_path / "out.mp4")}

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    first_frame = tmp_path / "first.png"
    last_frame = tmp_path / "last.png"
    first_frame.write_bytes(b"first")
    last_frame.write_bytes(b"last")

    node = node_module.Node()
    node.on_input(
        {"role": "user", "parts": [{"type": "text", "text": "生成镜头"}]},
        {
            "graph_id": "g1",
            "node_instance_id": "video3",
            "provider_id": "doubao-seedance-2-0-260128",
            "first_frame_path": str(first_frame),
            "last_frame_path": str(last_frame),
        },
    )

    content = dummy_agent.calls[0]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["role"] == "first_frame"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[2]["type"] == "image_url"
    assert content[2]["role"] == "last_frame"
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_video_generation_node_schema_exposes_seedance_safe_options():
    import nodes.video_generation_node as node_module

    node = node_module.Node()
    schema = node.config_schema

    assert "frames" not in schema
    assert "camera_fixed" not in schema
    assert schema["resolution"]["type"] == "select"
    assert [option["value"] for option in schema["resolution"]["options"]] == ["", "480p", "720p"]
    assert schema["duration"]["type"] == "select"
    assert schema["duration"]["options"][1]["value"] == "-1"
    assert schema["execution_expires_after"]["min"] == 3600
    assert schema["execution_expires_after"]["max"] == 259200
