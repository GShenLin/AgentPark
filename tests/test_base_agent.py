import tempfile

from src.base_agent import BaseAgent
import src.base_agent as base_agent_module


class DummyAgent(BaseAgent):
    def Send(self, tools=None, run_tools=None, mode=None):
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return msg.get("content")
        return ""


def test_makeplan_forwards_user_task_directly():
    with tempfile.TemporaryDirectory() as d:
        memory_path = d + "/dummy.md"
        agent = DummyAgent("dummy", memory_file_path=memory_path)
        out = agent.makePlan("hello world")
        assert out == "hello world"


def test_read_provider_config_from_file_reads_latest_model_config(monkeypatch):
    configs = iter(
        [
            {"type": "gemini", "apiKey": "first-key", "model": "first-model"},
            {"type": "gemini", "apiKey": "second-key", "model": "second-model"},
        ]
    )
    calls = []

    class DummyLoader:
        def get_provider_config(self, provider_name):
            calls.append(provider_name)
            return next(configs)

    monkeypatch.setattr(base_agent_module, "ConfigLoader", lambda: DummyLoader())

    with tempfile.TemporaryDirectory() as d:
        memory_path = d + "/dummy.md"
        agent = DummyAgent("dummy", memory_file_path=memory_path)

        first = agent._read_provider_config_from_file()
        second = agent._read_provider_config_from_file()
        agent.config = second

    assert first["model"] == "first-model"
    assert second["model"] == "second-model"
    assert agent.config["apiKey"] == "second-key"
    assert calls == ["dummy", "dummy"]
