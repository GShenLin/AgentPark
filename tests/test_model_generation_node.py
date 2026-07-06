import json


def test_model_generation_node_calls_provider_and_returns_files(monkeypatch, tmp_path):
    import nodes.model_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_3d_model(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "response": "done",
                "saved_files": [str(tmp_path / "model.glb"), str(tmp_path / "preview.webp")],
                "task_uuid": "task-1",
                "subscription_key": "sub-1",
                "status": "success",
            }

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    result = node.on_input(
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "A stylized wooden chest"},
                {"type": "resource", "resource": {"kind": "image", "uri": "https://cdn.example.com/chest.png"}},
            ],
        },
        {
            "graph_id": "g1",
            "node_instance_id": "model1",
            "provider_id": "hyper3d-rodin-gen2",
            "tier": "Gen-2",
            "use_original_alpha": True,
            "seed": "42",
            "geometry_file_format": "fbx",
            "material": "PBR",
            "quality": "high",
            "quality_override": "150000",
            "TAPose": "false",
            "bbox_width_y": "100",
            "bbox_height_z": "120",
            "bbox_length_x": "80",
            "mesh_mode": "Raw",
            "addons": "HighPack",
            "preview_render": True,
            "hd_texture": False,
            "filename_prefix": "asset",
        },
    )

    assert dummy_agent.calls
    call = dummy_agent.calls[0]
    assert call["prompt"] == "A stylized wooden chest"
    assert call["images"] == ["https://cdn.example.com/chest.png"]
    assert call["tier"] == "Gen-2"
    assert call["use_original_alpha"] is True
    assert call["seed"] == "42"
    assert call["geometry_file_format"] == "fbx"
    assert call["material"] == "PBR"
    assert call["quality"] == "high"
    assert call["quality_override"] == "150000"
    assert call["tapose"] == "false"
    assert call["bbox_condition"] == [100, 120, 80]
    assert call["mesh_mode"] == "Raw"
    assert call["addons"] == "HighPack"
    assert call["preview_render"] is True
    assert call["hd_texture"] is False
    assert call["filename_prefix"] == "asset"

    payload = result["routes"][0]["payload"]
    assert any(part.get("type") == "resource" and (part.get("resource") or {}).get("kind") == "file" for part in payload["parts"])
    assert "model.glb" in result["display"]


def test_model_generation_node_uses_configured_images(monkeypatch, tmp_path):
    import nodes.model_generation_node as node_module

    class DummyAgent:
        def __init__(self):
            self.calls = []

        def generate_3d_model(self, **kwargs):
            self.calls.append(kwargs)
            return {"response": "ok", "saved_files": [str(tmp_path / "out.glb")]}

    dummy_agent = DummyAgent()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: dummy_agent)

    node = node_module.Node()
    node.on_input(
        "",
        {
            "graph_id": "g1",
            "node_instance_id": "model2",
            "provider_id": "hyper3d-rodin-gen2",
            "prompt": "robot",
            "images": json.dumps(["C:/tmp/a.png", "C:/tmp/b.jpg"]),
        },
    )

    call = dummy_agent.calls[0]
    assert call["prompt"] == "robot"
    assert call["images"] == ["C:/tmp/a.png", "C:/tmp/b.jpg"]


def test_model_generation_node_schema_filters_model_generation_providers(monkeypatch, tmp_path):
    from src.config_loader import ConfigLoader
    import nodes.model_generation_node as node_module

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
                    "rodin": {
                        "type": "hyper3d",
                        "apiKey": "secret",
                        "baseUrl": "https://api.hyper3d.com/api/v2",
                        "model": "rodin",
                        "supportmode": ["model_generation"],
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
        assert [option["value"] for option in schema["provider_id"]["options"]] == ["rodin"]
        assert schema["geometry_file_format"]["type"] == "select"
        assert [option["value"] for option in schema["material"]["options"]] == ["", "PBR", "Shaded", "All", "None"]
        cfg = {}
        node.on_create(cfg, None)
        assert cfg["provider_id"] == "rodin"
    finally:
        ConfigLoader._instance = None


def test_hyper3d_runtime_builds_documented_body_fields():
    from src.providers.hyper3d_rodin_runtime import Hyper3DRodinRuntime

    class DummyHost:
        config = {}

    runtime = Hyper3DRodinRuntime(DummyHost())
    fields = runtime._build_fields(
        prompt="robot",
        tier="Gen-2",
        use_original_alpha="true",
        seed="42",
        geometry_file_format="obj",
        material="All",
        quality="medium",
        quality_override="18000",
        tapose=True,
        bbox_condition=[100, 120, 80],
        mesh_mode="Quad",
        addons="HighPack",
        preview_render=False,
        hd_texture=True,
    )

    payload = dict(fields)
    assert payload["tier"] == "Gen-2"
    assert payload["prompt"] == "robot"
    assert payload["use_original_alpha"] == "true"
    assert payload["seed"] == 42
    assert payload["geometry_file_format"] == "obj"
    assert payload["material"] == "All"
    assert payload["quality"] == "medium"
    assert payload["quality_override"] == 18000
    assert payload["TAPose"] == "true"
    assert payload["bbox_condition"] == "[100, 120, 80]"
    assert payload["mesh_mode"] == "Quad"
    assert payload["addons"] == '["HighPack"]'
    assert payload["preview_render"] == "false"
    assert payload["hd_texture"] == "true"


def test_hyper3d_runtime_request_json_uses_keyword_url(monkeypatch):
    import src.providers.hyper3d_runtime_base as runtime_base
    from src.providers.hyper3d_rodin_runtime import Hyper3DRodinRuntime

    calls = []

    def fake_request_json(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    class DummyHost:
        config = {"timeoutMs": 120000}

    monkeypatch.setattr(runtime_base, "request_json", fake_request_json)

    runtime = Hyper3DRodinRuntime(DummyHost())
    result = runtime._request_json(url="https://api.hyper3d.com/api/v2/rodin", headers={"A": "B"}, body=b"body")

    assert result == {"ok": True}
    assert calls[0]["url"] == "https://api.hyper3d.com/api/v2/rodin"
    assert calls[0]["method"] == "POST"
    assert calls[0]["headers"] == {"A": "B"}
    assert calls[0]["body"] == b"body"
    assert calls[0]["timeout_sec"] == 120


def test_hyper3d_runtime_base_resolves_poll_config_strictly():
    import pytest

    from src.providers.hyper3d_rodin_runtime import Hyper3DRodinRuntime

    class DummyHost:
        config = {"pollIntervalSec": "2.5", "modelGenerationPollIntervalSec": "7", "maxWaitSec": "0"}

    runtime = Hyper3DRodinRuntime(DummyHost())

    assert runtime._resolve_poll_interval_seconds("pollIntervalSec", "modelGenerationPollIntervalSec", default=5) == 2.5
    with pytest.raises(ValueError, match="maxWaitSec must be greater than 0"):
        runtime._resolve_max_wait_seconds("maxWaitSec", "modelGenerationMaxWaitSec", default=1800)
