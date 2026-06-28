import json

import pytest


def test_image_generation_node_calls_provider_and_returns_image(monkeypatch, tmp_path):
    import nodes.image_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_image(self, **kwargs):
            self.calls.append(kwargs)
            return str(tmp_path / "out.png")

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    result = node.on_input(
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "generate a product hero image"},
                {"type": "resource", "resource": {"kind": "image", "uri": "https://cdn.example.com/ref.png"}},
            ],
        },
        {
            "graph_id": "g1",
            "node_instance_id": "img1",
            "provider_id": "371NanoBanana",
            "aspect_ratio": "16:9",
            "image_size": "2K",
            "response_format": "b64_json",
            "watermark": "true",
            "filename_prefix": "hero",
        },
    )

    assert dummy_agent.calls
    call = dummy_agent.calls[0]
    assert call["prompt"] == "generate a product hero image"
    assert call["aspect_ratio"] == "16:9"
    assert call["image_size"] == "2K"
    assert call["size"] == "2K"
    assert call["response_format"] == "b64_json"
    assert call["watermark"] is True
    assert call["filename_prefix"] == "hero"
    assert call["image"] == ["https://cdn.example.com/ref.png"]

    payload = result["routes"][0]["payload"]
    parts = payload["parts"]
    assert any(part.get("type") == "resource" and (part.get("resource") or {}).get("kind") == "image" for part in parts)
    assert str(tmp_path / "out.png") in result["display"]


def test_image_generation_node_uses_configured_prompt_and_reference_images(monkeypatch, tmp_path):
    import nodes.image_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_image(self, **kwargs):
            self.calls.append(kwargs)
            return {"image_path": [str(tmp_path / "one.png"), str(tmp_path / "two.png")]}

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    node.on_input(
        "",
        {
            "graph_id": "g1",
            "node_instance_id": "img2",
            "provider_id": "gemini-2.5-flash-image",
            "prompt": "make a clean logo",
            "reference_images": json.dumps(["C:/tmp/ref-a.png", "C:/tmp/ref-b.png"]),
        },
    )

    call = dummy_agent.calls[0]
    assert call["prompt"] == "make a clean logo"
    assert call["image"] == ["C:/tmp/ref-a.png", "C:/tmp/ref-b.png"]


def test_image_generation_node_rejects_invalid_watermark(monkeypatch):
    import nodes.image_generation_node as node_module

    class DummyAgent:
        def generate_image(self, **_kwargs):
            raise AssertionError("generate_image should not be called")

    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = node_module.Node()
    with pytest.raises(ValueError, match="watermark must be a boolean value"):
        node.on_input(
            {"role": "user", "parts": [{"type": "text", "text": "generate"}]},
            {
                "graph_id": "g1",
                "node_instance_id": "img-invalid",
                "provider_id": "371NanoBanana",
                "watermark": "maybe",
            },
        )


def test_image_generation_node_schema_filters_image_generation_providers(monkeypatch, tmp_path):
    from src.config_loader import ConfigLoader
    import nodes.image_generation_node as node_module

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
                    "image-capable": {
                        "type": "doubao",
                        "apiKey": "secret",
                        "baseUrl": "https://example.com/v1",
                        "model": "image-model",
                        "supportmode": ["chat", "image_generation"],
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AITOOLS_CONFIG_PATH", str(config_path))
    ConfigLoader._instance = None
    ConfigLoader._config = None

    try:
        node = node_module.Node()
        schema = node.get_config_schema(None)

        assert schema["provider_id"]["type"] == "select"
        assert [option["value"] for option in schema["provider_id"]["options"]] == ["image-capable"]
        cfg = {}
        node.on_create(cfg, None)
        assert cfg["provider_id"] == "image-capable"
    finally:
        ConfigLoader._instance = None
        ConfigLoader._config = None
