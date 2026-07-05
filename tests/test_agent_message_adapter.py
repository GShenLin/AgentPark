def test_agent_user_content_compacts_large_local_image_and_preserves_path(tmp_path):
    from PIL import Image

    from nodes.agent_message_adapter import build_agent_user_content

    image_path = tmp_path / "cover.png"
    image = Image.effect_noise((1600, 2200), 64).convert("RGB")
    image.save(image_path)

    content = build_agent_user_content(
        "openai-test-provider",
        "imagechat",
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "检查这张封面图"},
                {"type": "resource", "resource": {"kind": "image", "uri": str(image_path), "source": "image_generation"}},
            ],
        },
        "",
    )

    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert f"[image] {image_path}" in content[0]["text"]

    image_url = content[1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert len(image_url) < 750_000


def test_imagechat_output_preserves_input_image_resource():
    from nodes.agent_message_adapter import append_input_resources_for_imagechat

    output = {
        "role": "assistant",
        "parts": [{"type": "text", "text": "封面可用"}],
    }
    input_message = {
        "role": "user",
        "parts": [
            {
                "type": "resource",
                "resource": {
                    "kind": "image",
                    "uri": "/tmp/cover.png",
                    "source": "image_generation",
                    "metadata": {"node": "cover_image_generator"},
                },
            }
        ],
    }

    result = append_input_resources_for_imagechat(output, input_message, "imagechat")
    resources = [part for part in result["parts"] if part.get("type") == "resource"]

    assert len(resources) == 1
    assert resources[0]["resource"]["kind"] == "image"
    assert resources[0]["resource"]["uri"] == "/tmp/cover.png"
    assert resources[0]["resource"]["source"] == "image_generation"


def test_chat_output_does_not_preserve_input_image_resource():
    from nodes.agent_message_adapter import append_input_resources_for_imagechat

    output = {
        "role": "assistant",
        "parts": [{"type": "text", "text": "回答文本"}],
    }
    input_message = {
        "role": "user",
        "parts": [{"type": "resource", "resource": {"kind": "image", "uri": "/tmp/inbound.jpg"}}],
    }

    result = append_input_resources_for_imagechat(output, input_message, "chat")

    assert not [part for part in result["parts"] if part.get("type") == "resource"]
