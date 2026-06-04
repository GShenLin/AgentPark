import pytest


def test_create_agent_uses_explicit_provider_type(monkeypatch):
    import src.providers as providers

    class DummyGemini:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt

    class DummyDoubao:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt

    class DummyHyper3D:
        def __init__(self, provider_id=None, memory_file_path=None, system_prompt=None):
            self.provider_id = provider_id
            self.memory_file_path = memory_file_path
            self.system_prompt = system_prompt

    class DummyLoader:
        def get_provider_config(self, provider_name):
            if provider_name == "p-gemini":
                return {"type": "gemini"}
            if provider_name == "p-hyper3d":
                return {"type": "hyper3d"}
            return {"type": "doubao"}

    monkeypatch.setattr(providers, "GeminiAgent", DummyGemini)
    monkeypatch.setattr(providers, "DouBaoAgent", DummyDoubao)
    monkeypatch.setattr(providers, "Hyper3DAgent", DummyHyper3D)
    monkeypatch.setattr(providers, "ConfigLoader", lambda: DummyLoader())

    gemini_agent = providers.create_agent("p-gemini", memory_file_path="m1", system_prompt="s1")
    doubao_agent = providers.create_agent("p-doubao", memory_file_path="m2", system_prompt="s2")
    hyper3d_agent = providers.create_agent("p-hyper3d", memory_file_path="m3", system_prompt="s3")

    assert isinstance(gemini_agent, DummyGemini)
    assert gemini_agent.provider_id == "p-gemini"
    assert isinstance(doubao_agent, DummyDoubao)
    assert doubao_agent.provider_id == "p-doubao"
    assert isinstance(hyper3d_agent, DummyHyper3D)
    assert hyper3d_agent.provider_id == "p-hyper3d"


def test_create_agent_rejects_unsupported_provider_type(monkeypatch):
    import src.providers as providers

    class DummyLoader:
        def get_provider_config(self, _provider_name):
            return {"type": "unknown"}

    monkeypatch.setattr(providers, "ConfigLoader", lambda: DummyLoader())

    with pytest.raises(ValueError):
        providers.create_agent("p-unknown")
