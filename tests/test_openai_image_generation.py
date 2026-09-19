import base64
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from src.providers.openai_agent import OpenAIAgent
from src.providers.openai_transport import OpenAITransport
from src.provider_auth.credentials import ProviderRequestCredentials


@pytest.fixture
def image_runtime(monkeypatch, tmp_path):
    from src.config_loader import ConfigLoader

    config = ConfigLoader().get_provider_config("GPT_Image_2_5")
    monkeypatch.setattr(OpenAIAgent, "_read_provider_config_from_file", lambda self: dict(config))
    monkeypatch.setattr("src.providers.openai_image_generation.resolve_provider_request_credentials",
                        lambda config: ProviderRequestCredentials(config["baseUrl"], {
                            "Authorization": "Bearer test", "ChatGPT-Account-ID": "test-account",
                        }))
    encoded = BytesIO()
    Image.new("RGB", (16, 16), "red").save(encoded, format="PNG")
    png = encoded.getvalue()
    calls = []
    response = {"created": 1, "data": [{"b64_json": base64.b64encode(png).decode("ascii")}]}

    def post(self, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(OpenAITransport, "_curl_post_json_once", post)
    agent = OpenAIAgent("GPT_Image_2_5", memory_file_path=str(tmp_path / "memory.md"),
                        internal_memory_enabled=False)
    agent.Message("user", "draw a red square", persist=False)
    return SimpleNamespace(agent=agent, calls=calls, response=response, png=png, folder=tmp_path)


def test_agent_send_generates_with_configured_model_and_persists_image(image_runtime):
    run = image_runtime
    result = run.agent.Send(mode="image_generation", mode_options={"image_filename_prefix": "test"})
    path = Path(result["image_path"])
    assert path.parent == run.folder / "generated_images"
    assert path.read_bytes() == run.png
    request, = run.calls
    assert request["url"] == "https://chatgpt.com/backend-api/codex/images/generations"
    assert request["timeout_sec"] == 180
    assert request["headers"] == {
        "Content-Type": "application/json", "Authorization": "Bearer test", "ChatGPT-Account-ID": "test-account",
    }
    assert json.loads(request["payload_json"]) == {
        "model": "gpt-image-2.5", "prompt": "draw a red square",
        "background": "auto", "quality": "auto", "size": "auto",
    }


def test_edit_uses_configured_and_attached_references(image_runtime):
    run = image_runtime
    reference = run.folder / "reference.png"
    reference.write_bytes(run.png)
    run.agent.Message("user", [
        {"type": "text", "text": "edit this"},
        {"type": "reference_resource", "kind": "image", "uri": reference.as_uri()},
    ], persist=False)
    run.agent.Send(mode="image_generation", mode_options={"image_references": ["https://example.com/reference.png"]})
    request, = run.calls
    assert request["url"].endswith("/images/edits")
    assert json.loads(request["payload_json"])["images"] == [
        {"image_url": "https://example.com/reference.png"},
        {"image_url": "data:image/png;base64," + base64.b64encode(run.png).decode("ascii")},
    ]


@pytest.mark.parametrize("data", [[], [{}], [{"b64_json": "invalid"}], [{"b64_json": "bm90IGFuIGltYWdl"}]])
def test_invalid_response_fails_without_persisting_images(image_runtime, data):
    run = image_runtime
    run.response["data"] = data
    with pytest.raises((ValueError, OSError)):
        run.agent.Send(mode="image_generation")
    assert not (run.folder / "generated_images").exists()


def test_invalid_prefix_fails_before_request(image_runtime):
    with pytest.raises(ValueError, match="filename"):
        image_runtime.agent.Send(mode="image_generation", mode_options={"image_filename_prefix": "../escape"})
    assert not image_runtime.calls


def test_agent_node_emits_image_resource_without_chat_history_or_memory(image_runtime, monkeypatch):
    import nodes.agent_node as module

    def unexpected(*args, **kwargs):
        pytest.fail("Image generation must not invoke chat history or long-term memory models")

    monkeypatch.setattr(module, "load_agent_history_messages", unexpected)
    monkeypatch.setattr(module, "prepare_node_memory", unexpected)
    result = module.Node().on_input("draw a red square", {
        "graph_id": "image-test", "node_instance_id": "image-node", "provider_id": "GPT_Image_2_5",
    })
    parts = result["display_message"]["parts"]
    resources = [part["resource"] for part in parts if part["type"] == "resource"]
    assert len(resources) == 1 and resources[0]["kind"] == "image"
    assert Path(resources[0]["uri"]).read_bytes() == image_runtime.png
    assert len(image_runtime.calls) == 1


def test_image_provider_schema_only_shows_supported_controls():
    from nodes.agent_node_contract import AGENT_CONFIG_SCHEMA
    from nodes.agent_node_schema import build_agent_config_schema

    schema = build_agent_config_schema(AGENT_CONFIG_SCHEMA, {"provider_id": "GPT_Image_2_5"})
    assert {key for key in schema if key.startswith("image_")} == {"image_references", "image_filename_prefix"}
    assert "reasoning_effort" not in schema
