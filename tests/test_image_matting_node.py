from __future__ import annotations

import os

import pytest
from PIL import Image

from src.providers.provider_errors import ProviderInputError


def test_image_matting_node_calls_selected_provider_and_returns_image(monkeypatch, tmp_path):
    import nodes.image_matting_node as node_module

    source = tmp_path / "source.png"
    output = tmp_path / "matted.png"
    Image.new("RGB", (32, 24), (100, 120, 140)).save(source)
    Image.new("RGBA", (32, 24), (100, 120, 140, 0)).save(output)

    class DummyProvider:
        def __init__(self):
            self.calls = []

        def matte_image(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "image_path": str(output),
                "status": "success",
                "model": "test-model",
                "model_revision": "test-revision",
                "width": 32,
                "height": 24,
                "alpha_min": 0,
                "alpha_max": 255,
            }

    provider = DummyProvider()
    monkeypatch.setattr(node_module, "create_agent", lambda *_args, **_kwargs: provider)

    node = node_module.Node()
    result = node.on_input(
        {
            "role": "user",
            "parts": [
                {"type": "resource", "resource": {"kind": "image", "uri": str(source)}},
                {"type": "meta", "meta": {"source": "test"}},
            ],
        },
        {
            "memory_path": str(tmp_path / "node" / "memory.md"),
            "method": "ai_matting",
            "provider_id": "matting-local",
            "filename_prefix": "subject",
        },
    )

    assert provider.calls == [
        {
            "image_path": os.path.abspath(source),
            "output_dir": str(tmp_path / "node" / "output"),
            "filename_prefix": "subject",
        }
    ]
    payload = result["routes"][0]["payload"]
    resource = next(part["resource"] for part in payload["parts"] if part["type"] == "resource")
    assert resource["kind"] == "image"
    assert resource["uri"] == str(output)
    assert resource["source"] == "image_matting"
    structured = next(part["data"] for part in payload["parts"] if part["type"] == "structured")
    assert structured["method"] == "ai_matting"
    assert structured["provider_id"] == "matting-local"


def test_image_matting_node_defaults_to_local_magic_wand(monkeypatch, tmp_path):
    import nodes.image_matting_node as node_module

    source = tmp_path / "source.png"
    image = Image.new("RGB", (32, 24), "white")
    for x in range(8, 24):
        for y in range(6, 18):
            image.putpixel((x, y), (30, 40, 50))
    image.save(source)

    def fail_create_agent(*_args, **_kwargs):
        raise AssertionError("Default Magic Wand Alpha must not create a provider.")

    monkeypatch.setattr(node_module, "create_agent", fail_create_agent)

    result = node_module.Node().on_input(
        {
            "role": "user",
            "parts": [
                {"type": "resource", "resource": {"kind": "image", "uri": str(source)}},
            ],
        },
        {
            "memory_path": str(tmp_path / "node" / "memory.md"),
            "filename_prefix": "subject",
        },
    )

    payload = result["routes"][0]["payload"]
    assert result["display_message"] == payload
    assert "display" not in result
    resource = next(part["resource"] for part in payload["parts"] if part["type"] == "resource")
    structured = next(part["data"] for part in payload["parts"] if part["type"] == "structured")
    with Image.open(resource["uri"]) as output:
        alpha = output.getchannel("A")
        assert alpha.getpixel((0, 0)) == 0
        assert alpha.getpixel((16, 12)) == 255
    assert structured["method"] == "magic_wand"
    assert structured["background_mode"] == "corners"
    assert structured["background_color"] == "#FFFFFF"
    assert structured["background_colors"] == ["#FFFFFF"]
    assert "provider_id" not in structured


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [{"type": "text", "text": "remove background"}],
        [
            {"type": "resource", "resource": {"kind": "image", "uri": "a.png"}},
            {"type": "resource", "resource": {"kind": "image", "uri": "b.png"}},
        ],
        [{"type": "resource", "resource": {"kind": "image", "uri": "https://example.com/a.png"}}],
    ],
)
def test_image_matting_node_rejects_non_single_local_image(parts):
    from nodes.image_matting_node import Node

    with pytest.raises(ProviderInputError):
        Node._extract_single_local_image({"role": "user", "parts": parts})


def test_image_matting_node_schema_filters_provider_support(monkeypatch):
    import nodes.image_matting_node as node_module

    monkeypatch.setattr(
        node_module,
        "build_provider_options_for_support_modes",
        lambda modes, **_kwargs: (
            [{"value": "matting-local", "label": "matting-local"}]
            if modes == {"image_matting"}
            else []
        ),
    )

    node = node_module.Node()
    schema = node.get_config_schema(None)
    config = {}
    node.on_create(config, None)
    ai_config = {"method": "ai_matting"}
    node.on_create(ai_config, None)

    assert schema["provider_id"]["type"] == "select"
    assert schema["provider_id"]["visible_when"] == {
        "field": "method",
        "equals": "ai_matting",
    }
    assert schema["background_color"]["type"] == "color"
    assert schema["background_color"]["default_color"] == "#FFFFFF"
    assert schema["background_color"]["auto_label"] == "Auto"
    for field in (
        "background_color",
        "tolerance",
        "edge_softness",
        "feather_px",
    ):
        assert schema[field]["visible_when"] == {
            "field": "method",
            "equals": "magic_wand",
        }
    assert config["method"] == "magic_wand"
    assert config["background_color"] == ""
    assert config["tolerance"] == 1
    assert config["edge_softness"] == 0
    assert config["feather_px"] == 0.0
    assert config["provider_id"] == ""
    assert ai_config["provider_id"] == "matting-local"
