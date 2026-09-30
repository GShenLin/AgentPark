"""Contract coverage against every registered implementation, without network calls."""
from dataclasses import replace
from functools import wraps
import inspect

import pytest

from src.providers import registry
from src.providers.agent_config import AgentConfig, AgentSendContext
from src.providers.agent_invocation import compile_agent_invocation, send_agent
from src.providers.parameter_mapping import PROVIDER_PARAMETER_MAPPINGS, ProviderParameterMapping


PROVIDERS = tuple(registry.PROVIDER_REGISTRATIONS)
INFERENCE = ("web_search", "thinking", "reasoning_effort", "reasoning_summary")


def provider_settings(kind, responses=True, model="test-model"):
    return {"type": kind, "responsesApi": responses, "model": model, "models": [model],
            "supportmode": ["chat"]}


def intercept_provider(monkeypatch, kind, settings):
    """Replace execution only; keep and enforce the actual implementation signatures."""
    cls = registry.PROVIDER_REGISTRATIONS[kind].load_class()
    original_init, original_send = cls.__init__, cls.Send
    calls = []

    @wraps(original_init)
    def init(self, *args, **kwargs):
        inspect.signature(original_init).bind(self, *args, **kwargs)
        self.creation = kwargs
        self.config = dict(settings)
        self.messages = []
        calls.append(self)

    @wraps(original_send)
    def send(self, *args, **kwargs):
        inspect.signature(original_send).bind(self, *args, **kwargs)
        self.received = kwargs
        return '{"summary":"mapped"}'

    monkeypatch.setattr(cls, "__init__", init)
    monkeypatch.setattr(cls, "Send", send)
    monkeypatch.setattr(registry.ConfigLoader, "get_provider_config", lambda *_: dict(settings))
    return cls, calls


def test_every_registered_provider_requires_an_explicit_complete_mapping():
    assert set(PROVIDER_PARAMETER_MAPPINGS) == set(PROVIDERS)


@pytest.mark.parametrize("kind", PROVIDERS)
@pytest.mark.parametrize("responses", [False, True])
def test_real_constructor_and_send_signatures_accept_compiled_configuration(kind, responses):
    cls = registry.PROVIDER_REGISTRATIONS[kind].load_class()
    config = AgentConfig(run_tools=False, web_search="disabled", thinking="enabled",
                         reasoning_effort="high", reasoning_summary="detailed", stream=True,
                         mode_options={"image_size": "2K"})
    invocation = compile_agent_invocation("test", provider_settings(kind, responses), config, cls)
    inspect.signature(cls.__init__).bind(None, **dict.fromkeys(invocation.mapping.constructor.values()))
    if invocation.mapping.supports_send:
        inspect.signature(cls.Send).bind(None, **invocation.send_kwargs)
    for name in config.values():
        target = invocation.mapping.send[name]
        assert (target in invocation.send_kwargs) != (name in invocation.excluded_fields)


@pytest.mark.parametrize("kind", PROVIDERS)
def test_factory_transfers_constructor_model_config_and_callbacks(kind, monkeypatch):
    settings = provider_settings(kind)
    cls, calls = intercept_provider(monkeypatch, kind, settings)
    config = AgentConfig(run_tools=False, web_search="enabled", thinking="enabled",
                         reasoning_effort="high", reasoning_summary="concise", stream=True,
                         mode_options={"image_size": "2K", "image_references": ["local.png"]})
    agent = registry.create_agent("test-id", memory_file_path="scratch.md", system_prompt="instructions",
                                  internal_memory_enabled=False, model_id="test-model", agent_config=config)
    assert isinstance(agent, cls)
    assert calls == [agent]
    assert agent.creation == {"provider_id": "test-id", "memory_file_path": "scratch.md",
                              "system_prompt": "instructions", "internal_memory_enabled": False}
    assert agent.selected_model_id == "test-model"
    assert agent.config["model"] == "test-model"
    if not agent._agent_invocation.mapping.supports_send:
        with pytest.raises(ValueError, match="explicit media"):
            send_agent(agent)
        assert "received" not in vars(agent)
        return
    stream = lambda *_: None
    thinking = lambda *_: None
    tools = [{"type": "function", "name": "test"}]
    assert send_agent(agent, AgentSendContext(tools=tools, stream_handler=stream,
                                            thinking_stream_handler=thinking)) == '{"summary":"mapped"}'
    expected = dict(agent._agent_invocation.send_kwargs)
    expected.update(tools=tools, stream_handler=stream)
    if agent._agent_invocation.mapping.send["thinking_stream_handler"] is not None:
        expected["thinking_stream_handler"] = thinking
    assert agent.received == expected
    assert agent.received["run_tools"] is False


@pytest.mark.parametrize("kind, responses, included", [
    ("openai", True, set(INFERENCE)),
    ("openai", False, {"thinking", "reasoning_effort"}),
    ("deepseek", True, {"thinking", "reasoning_effort", "reasoning_summary"}),
    ("deepseek", False, {"thinking", "reasoning_effort"}),
    ("doubao", True, {"web_search", "thinking", "reasoning_effort"}),
    ("doubao", False, set()),
    ("claude", False, {"web_search", "thinking", "reasoning_effort"}),
    ("gemini", False, set()),
    ("zhipu", False, {"thinking", "reasoning_effort"}),
    ("agnes", True, set(INFERENCE)),
    ("agnes", False, {"thinking", "reasoning_effort"}),
])
def test_model_transport_features_have_explicit_inclusion_or_exclusion(kind, responses, included):
    cls = registry.PROVIDER_REGISTRATIONS[kind].load_class()
    invocation = compile_agent_invocation("test", provider_settings(kind, responses), AgentConfig(
        web_search="enabled", thinking="enabled", reasoning_effort="high", reasoning_summary="detailed"), cls)
    assert set(invocation.send_kwargs) & set(INFERENCE) == included
    assert set(INFERENCE) - included <= set(invocation.excluded_fields)


@pytest.mark.parametrize("model, included", [
    ("kimi-k2.5", {"web_search", "thinking"}),
    ("kimi-k2.6", {"web_search", "thinking"}),
    ("kimi-k2.7-code", {"thinking"}),
    ("kimi-k3", {"web_search", "reasoning_effort"}),
])
def test_selected_kimi_model_changes_mapping(model, included):
    cls = registry.PROVIDER_REGISTRATIONS["kimi"].load_class()
    invocation = compile_agent_invocation("test", provider_settings("kimi", False, model), AgentConfig(
        web_search="enabled", thinking="enabled", reasoning_effort="max", reasoning_summary="concise"), cls)
    assert set(invocation.send_kwargs) & set(INFERENCE) == included


def test_explicit_source_to_destination_aliases_work_for_creation_and_send(monkeypatch):
    base = PROVIDER_PARAMETER_MAPPINGS["openai"]
    mapping = ProviderParameterMapping(
        {**base.constructor, "provider_id": "provider_name"},
        {**base.send, "reasoning_effort": "effort"},
    )

    class Aliased:
        def __init__(self, provider_name, memory_file_path, system_prompt, internal_memory_enabled):
            self.provider_name = provider_name
            self.config = {}

        def Send(self, *, effort, **kwargs):
            return effort

    monkeypatch.setitem(PROVIDER_PARAMETER_MAPPINGS, "openai", mapping)
    monkeypatch.setattr(registry, "import_module", lambda _: type("Module", (), {"OpenAIAgent": Aliased}))
    monkeypatch.setattr(registry.ConfigLoader, "get_provider_config",
                        lambda *_: provider_settings("openai"))
    agent = registry.create_agent("aliased-provider", agent_config=AgentConfig(reasoning_effort="high"))
    assert agent.provider_name == "aliased-provider"
    assert send_agent(agent) == "high"
    assert "reasoning_effort" not in agent._agent_invocation.send_kwargs


@pytest.mark.parametrize("field, value, error", [
    ("reasoning_summmary", "auto", TypeError),
    ("run_tools", "false", TypeError), ("stream", 1, TypeError),
    ("thinking", [], TypeError), ("web_search", "sometimes", ValueError),
    ("reasoning_effort", "extreme", ValueError), ("reasoning_summary", "yes", ValueError),
    ("mode_options", [], TypeError), ("mode", "", ValueError),
])
def test_invalid_generic_configuration_fails_before_provider_creation(field, value, error):
    with pytest.raises(error):
        AgentConfig(**{field: value})


def test_mapping_mismatch_is_an_error_not_a_filter_or_retry(monkeypatch):
    settings = provider_settings("doubao")
    cls, calls = intercept_provider(monkeypatch, "doubao", settings)
    base = PROVIDER_PARAMETER_MAPPINGS["doubao"]
    monkeypatch.setitem(PROVIDER_PARAMETER_MAPPINGS, "doubao", replace(
        base, send={**base.send, "reasoning_summary": "reasoning_summary"}))
    with pytest.raises(TypeError, match="does not match implementation.*reasoning_summary"):
        registry.create_agent("test", agent_config=AgentConfig(reasoning_summary="concise"))
    assert calls == []


def test_configuration_is_snapshotted_and_provider_mutation_does_not_leak(monkeypatch):
    cls, _ = intercept_provider(monkeypatch, "doubao", provider_settings("doubao"))
    options = {"image_references": ["original"]}
    agent = registry.create_agent("test", agent_config=AgentConfig(mode_options=options))
    options["image_references"].append("changed-after-creation")
    send_agent(agent)
    assert agent.received["mode_options"] == {"image_references": ["original"]}
    agent.received["mode_options"]["image_references"].append("provider-mutation")
    send_agent(agent)
    assert agent.received["mode_options"] == {"image_references": ["original"]}


def test_send_errors_are_propagated_once_and_never_retried(monkeypatch):
    cls, _ = intercept_provider(monkeypatch, "openai", provider_settings("openai"))
    agent = registry.create_agent("test")
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise TypeError("inside provider")

    agent.Send = fail
    with pytest.raises(TypeError, match="inside provider"):
        send_agent(agent)
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["doubao", "agnes"])
def test_media_web_search_is_independent_of_chat_transport(kind, monkeypatch):
    intercept_provider(monkeypatch, kind, provider_settings(kind, False))
    agent = registry.create_agent("test", agent_config=AgentConfig(
        mode="video_generation", web_search="enabled", mode_options={"video_duration": 5}))
    send_agent(agent)
    assert agent.received["web_search"] == "enabled"
    assert agent.received["mode_options"] == {"video_duration": 5}


@pytest.mark.parametrize("change", ["missing", "unknown", "duplicate", "constructor_none"])
def test_incomplete_or_ambiguous_mapping_is_rejected(change):
    base = PROVIDER_PARAMETER_MAPPINGS["openai"]
    constructor, send = dict(base.constructor), dict(base.send)
    if change == "missing":
        send.pop("stream")
    elif change == "unknown":
        send["mystery_option"] = "mystery_option"
    elif change == "duplicate":
        send["reasoning_summary"] = "reasoning_effort"
    else:
        constructor["provider_id"] = None
    with pytest.raises(ValueError):
        ProviderParameterMapping(constructor, send)


def test_new_required_provider_argument_is_detected_before_instantiation(monkeypatch):
    cls, calls = intercept_provider(monkeypatch, "openai", provider_settings("openai"))
    monkeypatch.setattr(cls, "Send", lambda self, *, new_required_field, **kwargs: None)
    with pytest.raises(TypeError, match="new_required_field"):
        registry.create_agent("test")
    assert not calls


@pytest.mark.parametrize("options", [{"run_tools": 1}, {"tools": {}}, {"stream_handler": "callback"}])
def test_invalid_runtime_controls_are_rejected_before_send(monkeypatch, options):
    _, calls = intercept_provider(monkeypatch, "openai", provider_settings("openai"))
    agent = registry.create_agent("test")
    with pytest.raises(TypeError):
        send_agent(agent, AgentSendContext(**options))
    assert "received" not in vars(calls[0])


def test_unknown_runtime_options_cannot_bypass_compiled_configuration():
    with pytest.raises(TypeError):
        AgentSendContext(reasoning_summary="concise")


def test_invalid_model_is_rejected_before_provider_constructor(monkeypatch):
    _, calls = intercept_provider(monkeypatch, "openai", provider_settings("openai"))
    with pytest.raises(ValueError, match="not allowed"):
        registry.create_agent("test", model_id="unlisted-model")
    assert not calls
