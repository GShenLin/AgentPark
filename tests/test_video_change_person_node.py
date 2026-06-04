import json


def test_video_change_person_node_calls_provider_and_returns_video(monkeypatch, tmp_path):
    import nodes.video_change_person_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_video_change_person(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "response": "done",
                "video_path": str(tmp_path / "out.mp4"),
                "video_url": "https://cdn.example.com/out.mp4",
                "task_id": "task-1",
                "status": "success",
                "video_duration": 5,
                "video_ratio": "16:9",
            }

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    result = node.on_input(
        {
            "role": "user",
            "parts": [
                {"type": "resource", "resource": {"kind": "image", "uri": "https://cdn.example.com/face.png"}},
                {"type": "resource", "resource": {"kind": "video", "uri": "https://cdn.example.com/source.mp4"}},
            ],
        },
        {
            "graph_id": "g1",
            "node_instance_id": "mix1",
            "provider_id": "wan2.2-animate-mix",
            "mode": "wan-pro",
            "watermark": "true",
            "check_image": False,
            "filename_prefix": "mix_video",
        },
    )

    assert dummy_agent.calls
    call = dummy_agent.calls[0]
    assert call["image_url"] == "https://cdn.example.com/face.png"
    assert call["video_url"] == "https://cdn.example.com/source.mp4"
    assert call["mode"] == "wan-pro"
    assert call["watermark"] == "true"
    assert call["check_image"] is False
    assert call["filename_prefix"] == "mix_video"

    payload = result["routes"][0]["payload"]
    parts = payload["parts"]
    assert any(
        part.get("type") == "resource"
        and (part.get("resource") or {}).get("kind") == "video"
        and str((part.get("resource") or {}).get("uri") or "").endswith("out.mp4")
        for part in parts
    )
    assert any(
        part.get("type") == "structured"
        and isinstance(part.get("data"), dict)
        and (part.get("data") or {}).get("video_ratio") == "16:9"
        for part in parts
    )


def test_video_change_person_node_converts_local_paths_to_public_urls(monkeypatch, tmp_path):
    import nodes.video_change_person_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_video_change_person(self, **kwargs):
            self.calls.append(kwargs)
            return {"response": "ok", "video_path": str(tmp_path / "out.mp4")}

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    image_path = tmp_path / "face.png"
    video_path = tmp_path / "source.mp4"
    image_path.write_bytes(b"png")
    video_path.write_bytes(b"mp4")

    node = node_module.Node()
    node.on_input(
        "",
        {
            "graph_id": "g1",
            "node_instance_id": "mix2",
            "provider_id": "wan2.2-animate-mix",
            "image_path": str(image_path),
            "video_path": str(video_path),
            "public_base_url": "https://public.example.com",
        },
    )

    call = dummy_agent.calls[0]
    assert call["image_url"].startswith("https://public.example.com/api/files/raw?path=")
    assert call["video_url"].startswith("https://public.example.com/api/files/raw?path=")


def test_video_change_person_node_schema_filters_supported_providers(monkeypatch, tmp_path):
    from src.config_loader import ConfigLoader
    import nodes.video_change_person_node as node_module

    config_path = tmp_path / "moduleProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "chat-only": {
                        "type": "doubao",
                        "apiKey": "secret",
                        "baseUrl": "https://example.com/v1",
                        "model": "chat-model",
                        "supportmode": ["chat"],
                    },
                    "video-mix": {
                        "type": "doubao",
                        "apiKey": "secret",
                        "baseUrl": "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2video/video-synthesis",
                        "model": "wan2.2-animate-mix",
                        "supportmode": ["video_changePerson"],
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AITOOLS_CONFIG_PATH", str(config_path))
    ConfigLoader._instance = None

    try:
        node = node_module.Node()
        schema = node.get_config_schema(None)
        assert schema["provider_id"]["type"] == "select"
        assert [option["value"] for option in schema["provider_id"]["options"]] == ["video-mix"]
        cfg = {}
        node.on_create(cfg, None)
        assert cfg["provider_id"] == "video-mix"
    finally:
        ConfigLoader._instance = None
