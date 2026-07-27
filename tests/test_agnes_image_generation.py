from src.providers.agnes_image_generation_contract import build_agnes_image_payload
from src.providers.registry import PROVIDER_REGISTRATIONS


def test_agnes_image_payload_places_provider_extensions_in_extra_body():
    payload = build_agnes_image_payload(
        model="agnes-image-2.0-flash",
        prompt="Create a product photograph",
        size="1024x768",
        response_format="url",
        image=["https://example.com/reference.png"],
    )

    assert payload == {
        "model": "agnes-image-2.0-flash",
        "prompt": "Create a product photograph",
        "size": "1024x768",
        "extra_body": {
            "response_format": "url",
            "image": ["https://example.com/reference.png"],
        },
    }
    assert "response_format" not in payload
    assert "image" not in payload


def test_agnes_provider_type_is_registered():
    registration = PROVIDER_REGISTRATIONS["agnes"]
    assert registration.load_class().__name__ == "AgnesAgent"


def test_agnes_agent_exposes_transport_and_both_generation_services():
    from src.providers.agnes_agent import AgnesAgent

    class FakeAgnes(AgnesAgent):
        def __init__(self):
            self._service_targets_cache = None

    service_names = [type(item).__name__ for item in FakeAgnes()._iter_service_targets()]
    assert service_names[:3] == [
        "DoubaoHttpTransport",
        "AgnesImageGeneration",
        "AgnesVideoGeneration",
    ]


def test_agnes_agent_accepts_chat_and_generation_modes(monkeypatch):
    from src.providers.agnes_agent import AgnesAgent
    from src.providers.openai_agent import OpenAIAgent

    monkeypatch.setattr(
        OpenAIAgent,
        "Send",
        lambda _self, *args, mode="chat", reasoning_summary=None, **kwargs: (
            mode,
            reasoning_summary,
        ),
    )
    agent = object.__new__(AgnesAgent)
    agent._read_provider_config_from_file = lambda: {}

    assert agent.Send(mode="chat", reasoning_summary="auto") == ("chat", "auto")
    assert agent.Send(mode="imagechat") == ("imagechat", None)


def test_agnes_image_generation_returns_paths_without_doubao_message_injection():
    from src.providers.agnes_agent import AgnesAgent

    agent = object.__new__(AgnesAgent)
    agent.messages = [{"role": "user", "content": "draw a lighthouse"}]
    agent.generate_image = lambda *_args, **_kwargs: "generated.png"

    result = agent._send_image_generation({})

    assert result == {
        "response": "Image generated successfully: generated.png",
        "image_path": "generated.png",
    }
    assert agent.messages == [{"role": "user", "content": "draw a lighthouse"}]
