from types import SimpleNamespace

from src.providers.openai_agent import OpenAIAgent


def _build_openai_agent(tmp_path):
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.test/v1",
        "model": "gpt-image-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "timeoutMs": 1000,
    }
    agent.provider_name = "openai"
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "agent.md"))
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda *_args, **_kwargs: None
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._service_targets_cache = None
    return agent


def test_openai_agent_generates_image_from_b64_response(tmp_path):
    agent = _build_openai_agent(tmp_path)
    calls = []

    def fake_post_json_with_retry(**kwargs):
        calls.append(kwargs)
        return {"data": [{"b64_json": "cG5n"}]}

    agent._post_json_with_retry = fake_post_json_with_retry

    result = agent.generate_image(
        prompt="draw a cover",
        response_format="b64_json",
        size="1K",
        aspect_ratio="3:4",
        filename_prefix="cover",
    )

    assert result.endswith(".png")
    assert calls[0]["url"] == "https://example.test/v1/images/generations"
    assert '"model": "gpt-image-test"' in calls[0]["payload_json"]
    assert '"size": "1024x1536"' in calls[0]["payload_json"]
    assert '"aspect_ratio": "3:4"' in calls[0]["payload_json"]
    assert agent.events[0]["stage"] == "openai_image_generation_start"


def test_openai_agent_keeps_explicit_pixel_size(tmp_path):
    agent = _build_openai_agent(tmp_path)
    calls = []

    def fake_post_json_with_retry(**kwargs):
        calls.append(kwargs)
        return {"data": [{"b64_json": "cG5n"}]}

    agent._post_json_with_retry = fake_post_json_with_retry

    agent.generate_image(
        prompt="draw a cover",
        response_format="b64_json",
        size="1024x1536",
        aspect_ratio="3:4",
        filename_prefix="cover",
    )

    assert '"size": "1024x1536"' in calls[0]["payload_json"]


def test_openai_agent_generates_image_from_data_url_response(tmp_path):
    agent = _build_openai_agent(tmp_path)

    def fake_post_json_with_retry(**_kwargs):
        return {"data": [{"url": "data:image/png;base64,cG5n"}]}

    agent._post_json_with_retry = fake_post_json_with_retry

    result = agent.generate_image(prompt="draw a cover", response_format="url")

    assert result.endswith(".png")
    with open(result, "rb") as handle:
        assert handle.read() == b"png"
