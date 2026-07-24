def test_agent_video_generation_schema_excludes_provider_owned_and_advanced_task_fields(monkeypatch):
    from nodes.agent_generation_schema import GENERATION_CONFIG_DEFAULTS
    from nodes.agent_node_contract import AGENT_CONFIG_SCHEMA
    from nodes.agent_node_modes import VIDEO_FIELDS
    from nodes.agent_node_schema import build_agent_config_schema

    removed_fields = {
        "video_model",
        "video_callback_url",
        "video_service_tier",
        "video_execution_expires_after",
        "video_safety_identifier",
    }
    monkeypatch.setattr(
        "nodes.agent_node_schema.ConfigLoader.get_all_providers",
        lambda _self: {
            "doubao-video": {
                "type": "doubao",
                "model": "doubao-seedance-2-0-260128",
                "supportmode": ["video_generation"],
            }
        },
    )

    schema = build_agent_config_schema(AGENT_CONFIG_SCHEMA, {"provider_id": "doubao-video"})

    assert removed_fields.isdisjoint(GENERATION_CONFIG_DEFAULTS)
    assert removed_fields.isdisjoint(AGENT_CONFIG_SCHEMA)
    assert removed_fields.isdisjoint(VIDEO_FIELDS)
    assert removed_fields.isdisjoint(schema)


def test_doubao_agent_does_not_forward_removed_video_node_options():
    from src.providers.doubao_agent import DouBaoAgent

    class Fake:
        messages = [{"role": "user", "content": [{"type": "text", "text": "make a video"}]}]

        def _read_provider_config_from_file(self):
            return {"model": "provider-video-model"}

        def _extract_latest_user_video_content(self, messages):
            return messages[-1]["content"]

        def generate_video(self, content, **kwargs):
            self.generated = {"content": content, **kwargs}
            return "output.mp4"

    fake = Fake()
    removed_fields = {
        "video_model": "node-model-override",
        "video_callback_url": "https://callback.example.com/video",
        "video_service_tier": "default",
        "video_execution_expires_after": 7200,
        "video_safety_identifier": "user-hash",
    }

    DouBaoAgent.Send(fake, mode="video_generation", mode_options=removed_fields)

    assert set(removed_fields).isdisjoint(fake.generated)


def test_agent_node_builds_doubao_video_generation_content():
    from nodes.agent_message_adapter import build_agent_user_content

    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "做一个广告视频"},
            {"type": "resource", "resource": {"kind": "image", "uri": "https://cdn.example.com/ref.png"}},
            {"type": "resource", "resource": {"kind": "video", "uri": "asset://video-1"}},
            {"type": "resource", "resource": {"kind": "audio", "uri": "https://cdn.example.com/ref.mp3"}},
        ],
    }

    content = build_agent_user_content("doubao-seedance-2-0-260128", "video_generation", message, "")

    assert content == [
        {"type": "text", "text": "做一个广告视频"},
        {"type": "image_url", "image_url": {"url": "https://cdn.example.com/ref.png"}, "role": "reference_image"},
        {"type": "video_url", "video_url": {"url": "asset://video-1"}, "role": "reference_video"},
        {"type": "audio_url", "audio_url": {"url": "https://cdn.example.com/ref.mp3"}, "role": "reference_audio"},
    ]


def test_agent_node_accepts_local_image_for_video_generation_without_public_base_url(tmp_path):
    from nodes.agent_message_adapter import build_agent_user_content

    image_path = tmp_path / "local.png"
    image_path.write_bytes(b"png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "做一个广告视频"},
            {"type": "resource", "resource": {"kind": "image", "uri": str(image_path)}},
        ],
    }

    content = build_agent_user_content(
        "doubao-seedance-2-0-260128",
        "video_generation",
        message,
        "",
    )

    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_agent_node_outputs_video_resource(monkeypatch):
    import nodes.agent_node as agent_node_module

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            return {
                "response": "video ready",
                "video_path": "C:\\tmp\\video.mp4",
                "task_id": "task-1",
            }

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    result = node.on_input(
        "hello",
        {
            "graph_id": "g_video_unit",
            "node_instance_id": "n_video_unit",
            "provider_id": "doubao-seedance-2-0-260128",
            "mode": "video_generation",
        },
    )

    payload = ((result.get("routes") or [])[0] or {}).get("payload") or {}
    parts = payload.get("parts") or []
    assert any(part.get("type") == "text" and part.get("text") == "video ready" for part in parts if isinstance(part, dict))
    assert any(
        (part.get("resource") or {}).get("kind") == "video"
        and (part.get("resource") or {}).get("uri") == "C:\\tmp\\video.mp4"
        for part in parts
        if isinstance(part, dict) and part.get("type") == "resource"
    )
