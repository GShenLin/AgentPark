import pytest


def test_create_agent_uses_explicit_provider_type(monkeypatch):
    import src.providers as providers

    class DummyGemini:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyDoubao:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyClaude:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyHyper3D:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyOpenAI:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyDeepSeek:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyGrok:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyZhipu:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt
            self.internal_memory_enabled = internal_memory_enabled

    class DummyLoader:
        def get_provider_config(self, provider_name):
            if provider_name == "p-gemini":
                return {"type": "gemini"}
            if provider_name == "p-hyper3d":
                return {"type": "hyper3d"}
            if provider_name == "p-openai":
                return {"type": "openai"}
            if provider_name == "p-deepseek":
                return {"type": "deepseek"}
            if provider_name == "p-grok":
                return {"type": "grok"}
            if provider_name == "p-claude":
                return {"type": "claude"}
            if provider_name == "p-zhipu":
                return {"type": "zhipu"}
            return {"type": "doubao"}

    monkeypatch.setattr(providers, "GeminiAgent", DummyGemini)
    monkeypatch.setattr(providers, "DouBaoAgent", DummyDoubao)
    monkeypatch.setattr(providers, "ClaudeAgent", DummyClaude)
    monkeypatch.setattr(providers, "Hyper3DAgent", DummyHyper3D)
    monkeypatch.setattr(providers, "OpenAIAgent", DummyOpenAI)
    monkeypatch.setattr(providers, "DeepSeekAgent", DummyDeepSeek)
    monkeypatch.setattr(providers, "GrokAgent", DummyGrok)
    monkeypatch.setattr(providers, "ZhipuAgent", DummyZhipu)
    monkeypatch.setattr(providers, "ConfigLoader", lambda: DummyLoader())

    gemini_agent = providers.create_agent("p-gemini", memory_file_path="m1", system_prompt="s1")
    doubao_agent = providers.create_agent("p-doubao", memory_file_path="m2", system_prompt="s2")
    claude_agent = providers.create_agent("p-claude", memory_file_path="m3", system_prompt="s3")
    hyper3d_agent = providers.create_agent("p-hyper3d", memory_file_path="m4", system_prompt="s4")
    openai_agent = providers.create_agent("p-openai", memory_file_path="m5", system_prompt="s5")
    deepseek_agent = providers.create_agent("p-deepseek", memory_file_path="m7", system_prompt="s7")
    grok_agent = providers.create_agent("p-grok", memory_file_path="m8", system_prompt="s8")
    zhipu_agent = providers.create_agent("p-zhipu", memory_file_path="m6", system_prompt="s6")

    assert isinstance(gemini_agent, DummyGemini)
    assert gemini_agent.provider_id == "p-gemini"
    assert isinstance(doubao_agent, DummyDoubao)
    assert doubao_agent.provider_id == "p-doubao"
    assert isinstance(claude_agent, DummyClaude)
    assert claude_agent.provider_id == "p-claude"
    assert isinstance(hyper3d_agent, DummyHyper3D)
    assert hyper3d_agent.provider_id == "p-hyper3d"
    assert isinstance(openai_agent, DummyOpenAI)
    assert openai_agent.provider_id == "p-openai"
    assert isinstance(deepseek_agent, DummyDeepSeek)
    assert deepseek_agent.provider_id == "p-deepseek"
    assert isinstance(grok_agent, DummyGrok)
    assert grok_agent.provider_id == "p-grok"
    assert isinstance(zhipu_agent, DummyZhipu)
    assert zhipu_agent.provider_id == "p-zhipu"

    no_memory_agent = providers.create_agent("p-zhipu", internal_memory_enabled=False)
    assert no_memory_agent.internal_memory_enabled is False


def test_create_agent_rejects_unsupported_provider_type(monkeypatch):
    import src.providers as providers

    class DummyLoader:
        def get_provider_config(self, _provider_name):
            return {"type": "unknown"}

    monkeypatch.setattr(providers, "ConfigLoader", lambda: DummyLoader())

    with pytest.raises(ValueError):
        providers.create_agent("p-unknown")
