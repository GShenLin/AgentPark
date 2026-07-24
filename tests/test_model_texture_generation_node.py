import json


def test_model_texture_generation_node_calls_provider_and_returns_files(monkeypatch, tmp_path):
    import nodes.model_texture_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_3d_texture(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "response": "done",
                "saved_files": [str(tmp_path / "textured.glb")],
                "task_uuid": "texture-task",
                "subscription_key": "texture-sub",
                "status": "success",
            }

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    result = node.on_input(
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "white silk and pale hair material"},
                {"type": "resource", "resource": {"kind": "file", "uri": "C:/tmp/character.glb"}},
                {"type": "resource", "resource": {"kind": "image", "uri": "C:/tmp/ref.png"}},
            ],
        },
        {
            "graph_id": "g1",
            "node_instance_id": "texture1",
            "provider_id": "hyper3d-rodin-gen2",
            "seed": "7",
            "reference_scale": "1.25",
            "geometry_file_format": "glb",
            "material": "PBR",
            "resolution": "High",
            "filename_prefix": "textured_asset",
        },
    )

    assert dummy_agent.calls
    call = dummy_agent.calls[0]
    assert call["model_path"] == "C:/tmp/character.glb"
    assert call["image_path"] == "C:/tmp/ref.png"
    assert call["prompt"] == "white silk and pale hair material"
    assert call["seed"] == "7"
    assert call["reference_scale"] == "1.25"
    assert call["geometry_file_format"] == "glb"
    assert call["material"] == "PBR"
    assert call["resolution"] == "High"
    assert call["filename_prefix"] == "textured_asset"

    payload = result["routes"][0]["payload"]
    assert any(part.get("type") == "resource" and (part.get("resource") or {}).get("kind") == "file" for part in payload["parts"])
    assert "textured.glb" in result["display"]


def test_model_texture_generation_node_uses_configured_paths(monkeypatch, tmp_path):
    import nodes.model_texture_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_3d_texture(self, **kwargs):
            self.calls.append(kwargs)
            return {"response": "ok", "saved_files": [str(tmp_path / "out.glb")]}

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    node.on_input(
        "",
        {
            "graph_id": "g1",
            "node_instance_id": "texture2",
            "provider_id": "hyper3d-rodin-gen2",
            "model_path": "C:/tmp/model.obj",
            "image_path": "C:/tmp/texture.jpg",
            "prompt": "aged bronze",
        },
    )

    call = dummy_agent.calls[0]
    assert call["model_path"] == "C:/tmp/model.obj"
    assert call["image_path"] == "C:/tmp/texture.jpg"
    assert call["prompt"] == "aged bronze"


def test_model_texture_generation_node_schema_filters_texture_providers(monkeypatch, tmp_path):
    from src.config_loader import ConfigLoader
    import nodes.model_texture_generation_node as node_module

    config_path = tmp_path / "modelProvider.json"
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
                    "rodin-texture": {
                        "type": "hyper3d",
                        "apiKey": "secret",
                        "baseUrl": "https://api.hyper3d.com/api/v2",
                        "model": "rodin",
                        "supportmode": ["model_texture_generation"],
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    ConfigLoader._instance = None

    try:
        node = node_module.Node()
        schema = node.get_config_schema(None)

        assert schema["provider_id"]["type"] == "select"
        assert [option["value"] for option in schema["provider_id"]["options"]] == ["rodin-texture"]
        assert [option["value"] for option in schema["resolution"]["options"]] == ["", "Basic", "High"]
        cfg = {}
        node.on_create(cfg, None)
        assert cfg["provider_id"] == "rodin-texture"
    finally:
        ConfigLoader._instance = None


def test_hyper3d_texture_runtime_builds_documented_body_fields():
    from src.providers.hyper3d_texture_runtime import Hyper3DTextureRuntime

    class DummyHost:
        config = {}

    runtime = Hyper3DTextureRuntime(DummyHost())
    fields = runtime._build_fields(
        prompt="blue fabric",
        seed="99",
        reference_scale="1.5",
        geometry_file_format="fbx",
        material="Shaded",
        resolution="High",
    )

    payload = dict(fields)
    assert payload["prompt"] == "blue fabric"
    assert payload["seed"] == 99
    assert payload["reference_scale"] == 1.5
    assert payload["geometry_file_format"] == "fbx"
    assert payload["material"] == "Shaded"
    assert payload["resolution"] == "High"
