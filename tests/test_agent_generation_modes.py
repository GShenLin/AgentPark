from pathlib import Path


def test_image_generation_input_merges_message_and_configured_references():
    from src.providers.image_generation_input import latest_image_generation_input

    prompt, references = latest_image_generation_input(
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": "make it cinematic"},
                {"type": "reference_resource", "kind": "image", "uri": "input.png"},
                {"type": "image_url", "image_url": {"url": "https://example.com/ref.png"}},
            ],
        }],
        '["configured.png", "input.png"]',
    )

    assert prompt == "make it cinematic"
    assert references == ["configured.png", "input.png", "https://example.com/ref.png"]


def test_agent_message_adapter_preserves_image_generation_references():
    from nodes.agent_message_adapter import build_agent_user_content

    content = build_agent_user_content(
        "doubao",
        "image_generation",
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "draw this"},
                {"type": "resource", "resource": {"kind": "image", "uri": "C:/ref.png"}},
            ],
        },
    )

    assert content == [
        {"type": "text", "text": "draw this"},
        {"type": "reference_resource", "kind": "image", "uri": "C:/ref.png"},
    ]


def test_doubao_agent_forwards_image_mode_options_and_references():
    from src.providers.doubao_agent import DouBaoAgent

    class Fake:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "prompt"},
                {"type": "reference_resource", "kind": "image", "uri": "input.png"},
            ],
        }]
        injected = []

        def _read_provider_config_from_file(self):
            return {"model": "default"}

        def generate_image(self, prompt, **kwargs):
            self.generated = {"prompt": prompt, **kwargs}
            return "output.png"

        def _inject_image_message(self, path):
            self.injected.append(path)

    fake = Fake()
    result = DouBaoAgent.Send(fake, mode="image_generation", mode_options={
        "image_references": '["configured.png"]',
        "image_size": "4K",
    })

    assert fake.generated["prompt"] == "prompt"
    assert fake.generated["image"] == ["configured.png", "input.png"]
    assert "model" not in fake.generated
    assert fake.generated["size"] == "4K"
    assert result["image_path"] == "output.png"


def test_seedream_5_pro_payload_matches_documented_request_contract():
    from src.providers.doubao_image_generation_contract import build_seedream_image_payload

    payload = build_seedream_image_payload(
        model="doubao-seedream-5-0-pro-260628",
        prompt="draw a precise product hero",
        size="2048x1024",
        response_format="b64_json",
        watermark=False,
        image=["https://example.com/a.png", "https://example.com/b.png"],
        optimize_prompt_mode="fast",
        output_format="png",
        sequential_image_generation="disabled",
        stream=False,
    )

    assert payload == {
        "model": "doubao-seedream-5-0-pro-260628",
        "prompt": "draw a precise product hero",
        "size": "2048x1024",
        "response_format": "b64_json",
        "watermark": False,
        "image": ["https://example.com/a.png", "https://example.com/b.png"],
        "optimize_prompt_options": {"mode": "fast"},
        "output_format": "png",
    }


def test_seedream_5_pro_rejects_unsupported_or_invalid_image_options():
    import pytest

    from src.providers.doubao_image_generation_contract import build_seedream_image_payload

    common = {"model": "doubao-seedream-5-0-pro-260628", "prompt": "draw"}
    with pytest.raises(ValueError, match="not supported"):
        build_seedream_image_payload(**common, sequential_image_generation="auto")
    with pytest.raises(ValueError, match="requires 921600..4624220"):
        build_seedream_image_payload(**common, size="512x512")
    with pytest.raises(ValueError, match="at most 10"):
        build_seedream_image_payload(**common, image=[f"https://example.com/{index}.png" for index in range(11)])


def test_seedream_5_pro_agent_schema_only_exposes_supported_documented_fields(monkeypatch):
    from nodes.agent_node_contract import AGENT_CONFIG_SCHEMA
    from nodes.agent_image_generation_schema import IMAGE_CONFIG_DEFAULTS
    from nodes.agent_node_schema import build_agent_config_schema

    monkeypatch.setattr(
        "nodes.agent_node_schema.ConfigLoader.get_all_providers",
        lambda _self: {
            "doubao-seedream-5": {
                "type": "doubao",
                "model": "doubao-seedream-5-0-pro-260628",
                "supportmode": ["image_generation"],
            }
        },
    )

    schema = build_agent_config_schema(AGENT_CONFIG_SCHEMA, {"provider_id": "doubao-seedream-5"})
    image_keys = {key for key in schema if key.startswith("image_")}

    assert image_keys == {
        "image_references",
        "image_size",
        "image_optimize_prompt_mode",
        "image_output_format",
        "image_response_format",
        "image_watermark",
        "image_filename_prefix",
    }
    assert schema["image_references"]["type"] == "file_list"
    assert IMAGE_CONFIG_DEFAULTS["image_references"] == []
    assert schema["image_size"]["type"] == "image_dimensions"
    assert [item["value"] for item in schema["image_size"]["options"]] == ["1K", "2K"]
    assert schema["image_size"]["aspect_ratio_field"] == ""
    assert schema["image_size"]["custom_dimensions_supported"] is True
    assert schema["image_size"]["min_pixels"] == 921_600
    assert schema["image_size"]["max_pixels"] == 4_624_220
    assert [item["value"] for item in schema["image_optimize_prompt_mode"]["options"]] == [
        "", "standard", "fast",
    ]
    assert schema["image_size"]["modes"] == ["image_generation"]


def test_gemini_uses_shared_image_dimensions_schema_with_provider_contract():
    from nodes.agent_image_generation_schema import IMAGE_CONFIG_SCHEMA, materialize_image_generation_schema

    schema = materialize_image_generation_schema(
        IMAGE_CONFIG_SCHEMA,
        {"type": "gemini", "model": "gemini-3.1-flash-image"},
    )

    assert schema["image_size"]["type"] == "image_dimensions"
    assert [item["value"] for item in schema["image_size"]["options"]] == ["1K", "2K", "4K"]
    assert schema["image_size"]["aspect_ratio_field"] == "image_aspect_ratio"
    assert schema["image_size"]["custom_dimensions_supported"] is False
    assert schema["image_aspect_ratio"]["hidden"] is True


def test_seedream_4_5_schema_exposes_sequence_contract_but_not_unsupported_fields():
    from nodes.agent_image_generation_schema import IMAGE_CONFIG_SCHEMA, materialize_image_generation_schema

    schema = materialize_image_generation_schema(
        IMAGE_CONFIG_SCHEMA,
        {"type": "doubao", "model": "doubao-seedream-4-5-251128"},
    )

    assert [item["value"] for item in schema["image_size"]["options"]] == ["2K", "4K"]
    assert [item["value"] for item in schema["image_optimize_prompt_mode"]["options"]] == ["", "standard"]
    assert schema["image_max_images"]["visible_when"] == {
        "field": "image_sequential_image_generation",
        "equals": "auto",
    }
    assert "image_stream" in schema
    assert "image_output_format" not in schema
    assert "image_tools" not in schema


def test_seedream_5_lite_real_model_id_exposes_all_documented_capabilities():
    from nodes.agent_image_generation_schema import IMAGE_CONFIG_SCHEMA, materialize_image_generation_schema
    from src.providers.doubao_image_generation_contract import seedream_image_capabilities

    model = "doubao-seedream-5-0-260128"
    capabilities = seedream_image_capabilities(model)
    schema = materialize_image_generation_schema(
        IMAGE_CONFIG_SCHEMA,
        {"type": "doubao", "model": model},
    )

    assert capabilities is not None
    assert capabilities.family == "seedream-5.0-lite"
    assert capabilities.supports_sequential_images is True
    assert capabilities.supports_stream is True
    assert capabilities.supports_web_search is True
    assert [item["value"] for item in schema["image_size"]["options"]] == ["2K", "3K", "4K"]
    assert [item["value"] for item in schema["image_optimize_prompt_mode"]["options"]] == ["", "standard"]
    assert "image_output_format" in schema
    assert "image_sequential_image_generation" in schema
    assert "image_max_images" in schema
    assert "image_stream" in schema
    assert "image_tools" in schema


def test_additional_seedream_providers_clone_pro_settings_except_model_and_timeout():
    import json

    providers = json.loads(
        (Path(__file__).parents[1] / "config" / "modelProvider.json").read_text(encoding="utf-8")
    )["providers"]
    base = providers["doubao-seedream-5"]
    expected = {
        "doubao-seedream-5-lite": {
            "model": "doubao-seedream-5-0-260128",
            "timeoutMs": 60000,
        },
        "doubao-seedream-4-0-250828": {
            "model": "doubao-seedream-4-0-250828",
            "timeoutMs": 60000,
        },
    }

    for provider_id, expected_fields in expected.items():
        provider = providers[provider_id]
        assert provider["model"] == expected_fields["model"]
        assert provider["timeoutMs"] == expected_fields["timeoutMs"]
        assert {key: value for key, value in provider.items() if key not in {"model", "timeoutMs"}} == {
            key: value for key, value in base.items() if key not in {"model", "timeoutMs"}
        }


def test_seedream_providers_resolve_plain_text_to_image_generation():
    import json

    from nodes.agent_node_modes import resolve_input_support_mode

    providers = json.loads(
        (Path(__file__).parents[1] / "config" / "modelProvider.json").read_text(encoding="utf-8")
    )["providers"]
    message = {"role": "user", "parts": [{"type": "text", "text": "draw a girl"}]}

    for provider_id in (
        "doubao-seedream-4-5-251128",
        "doubao-seedream-5",
        "doubao-seedream-5-lite",
        "doubao-seedream-4-0-250828",
    ):
        support_modes = providers[provider_id]["supportmode"]
        assert support_modes == ["image_generation"]
        assert providers[provider_id]["imageGenerationTimeoutMs"] == 180000
        assert providers[provider_id]["imageGenerationMaxRetries"] == 0
        assert resolve_input_support_mode(support_modes, message) == "image_generation"


def test_gemini_agent_forwards_image_mode_options_and_returns_resource_dict():
    from src.providers.gemini_agent import GeminiAgent

    class Fake:
        messages = [{"role": "user", "content": [{"type": "text", "text": "prompt"}]}]

        def _read_provider_config_from_file(self):
            return {"model": "default"}

        def generate_image(self, prompt, **kwargs):
            self.generated = {"prompt": prompt, **kwargs}
            return {"image_path": ["one.png", "two.png"], "status": "success"}

    fake = Fake()
    result = GeminiAgent.Send(fake, mode="image_generation", mode_options={
        "image_aspect_ratio": "16:9",
    })

    assert "model" not in fake.generated
    assert fake.generated["aspect_ratio"] == "16:9"
    assert result == {
        "response": "Image generated successfully: one.png, two.png",
        "image_path": ["one.png", "two.png"],
    }


def test_gemini_image_chat_requests_and_preserves_text_and_images(monkeypatch):
    import json

    from src.providers.gemini_agent import GeminiAgent

    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "candidates": [{
                    "content": {
                        "parts": [
                            {"text": "Here is the image."},
                            {"inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}},
                        ]
                    }
                }]
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    class Fake:
        tool_declarations = []
        messages = []

        def _read_provider_config_from_file(self):
            return {
                "apiKey": "test-key",
                "baseUrl": "https://example.test/v1",
                "model": "gemini-image-test",
                "maxRetries": 0,
                "timeoutMs": 1000,
            }

        def _get_messages_with_memory(self):
            return [{"role": "user", "content": "draw while we chat"}]

        def _pick_candidate_content(self, candidates, _run_tools):
            return candidates[0], 0

        def _extract_candidate_calls_and_text(self, parts):
            texts = [str(part.get("text")) for part in parts if isinstance(part, dict) and part.get("text")]
            return [], "".join(texts), bool(texts)

        def save_inline_images(self, parts, filename_prefix):
            captured["saved_parts"] = parts
            captured["filename_prefix"] = filename_prefix
            return ["chat-image.png"]

        def Message(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("src.providers.gemini_agent.urllib.request.urlopen", fake_urlopen)

    result = GeminiAgent.Send(Fake(), mode="imagechat")

    assert captured["payload"]["generationConfig"] == {"responseModalities": ["TEXT", "IMAGE"]}
    assert captured["filename_prefix"] == "generated_image"
    assert result == {"response": "Here is the image.", "image_path": "chat-image.png"}


def test_gemini_image_chat_stream_preserves_inline_images(monkeypatch):
    import json

    from src.providers.gemini_stream_runtime import GeminiStreamRuntime

    image_part = {"inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}}
    event = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "done"}, image_part]}}]
    }).encode("utf-8")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter([b"data: " + event + b"\n"])

    class Host:
        config = {}

        def _parse_sse_json_event(self, data, stage):
            assert stage == "gemini_stream_parse"
            return json.loads(data)

        def _extract_candidate_calls_and_text(self, parts):
            texts = [str(part.get("text")) for part in parts if isinstance(part, dict) and part.get("text")]
            return [], "".join(texts), bool(texts)

        def _emit_stream_text(self, *_args):
            return None

    monkeypatch.setattr("src.providers.gemini_stream_runtime.urllib.request.urlopen", lambda *_args, **_kwargs: Response())

    result = GeminiStreamRuntime(Host())._stream_generate_content_once(
        url="https://example.test",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=None,
    )

    assert result == {"candidates": [{"content": {"parts": [{"text": "done"}, image_part]}}]}


def test_standalone_generation_node_types_are_removed():
    root = Path(__file__).parents[1]
    assert not (root / "nodes" / "image_generation_node.py").exists()
    assert not (root / "nodes" / "video_generation_node.py").exists()
    for relative_path in (
        "README.md",
        "README.zh.md",
        "docs/architecture/agentpark-architecture-overview.md",
    ):
        content = (root / relative_path).read_text(encoding="utf-8")
        assert "image_generation_node" not in content
        assert "video_generation_node" not in content
