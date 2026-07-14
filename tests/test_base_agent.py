import tempfile
from pathlib import Path

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


def test_internal_memory_disabled_skips_tail_injection_and_persistence():
    with tempfile.TemporaryDirectory() as d:
        memory_path = Path(d) / "dummy.md"
        memory_path.write_text("old memory tail", encoding="utf-8")

        agent = DummyAgent("dummy", memory_file_path=str(memory_path), internal_memory_enabled=False)
        agent.Message("assistant", "new answer")

        assert not any("[Memory Tail]" in str(msg.get("content") or "") for msg in agent.messages)
        assert memory_path.read_text(encoding="utf-8") == "old memory tail"


def test_internal_memory_disabled_preserves_explicit_message_history():
    with tempfile.TemporaryDirectory() as d:
        memory_path = Path(d) / "dummy.md"
        agent = DummyAgent("dummy", memory_file_path=str(memory_path), internal_memory_enabled=False)
        agent.Message("system", "node system", persist=False)
        agent.Message("user", "old question", persist=False)
        agent.Message("assistant", "old answer", persist=False)
        agent.Message("tool", "tool result", persist=False, tool_call_id="call-1", name="read_file")
        agent.Message("user", "new question", persist=False)

        messages = agent._get_messages_with_memory()

        assert [item["content"] for item in messages] == [
            "node system",
            "old question",
            "old answer",
            "tool result",
            "new question",
        ]
        assert messages[3]["role"] == "tool"
        assert messages[3]["tool_call_id"] == "call-1"


def test_assistant_progress_persists_via_bound_callback_without_entering_messages():
    with tempfile.TemporaryDirectory() as d:
        memory_path = Path(d) / "dummy.md"
        agent = DummyAgent("dummy", memory_file_path=str(memory_path), internal_memory_enabled=False)
        calls = []
        agent._agentpark_persist_assistant_progress = lambda message: calls.append(dict(message))

        tool_calls = [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ]
        agent.AssistantProgress("I will inspect that first.", tool_calls=tool_calls)

        assert calls == [
            {
                "role": "assistant_progress",
                "content": "I will inspect that first.",
                "context_policy": "exclude",
                "tool_calls": tool_calls,
            }
        ]
        assert agent.messages == []
        assert memory_path.exists() is False


def test_assistant_progress_does_not_persist_blank_content():
    with tempfile.TemporaryDirectory() as d:
        agent = DummyAgent("dummy", memory_file_path=str(Path(d) / "dummy.md"), internal_memory_enabled=False)
        calls = []
        agent._agentpark_persist_assistant_progress = lambda message: calls.append(dict(message))
        tool_calls = [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ]

        agent.AssistantProgress("", tool_calls=tool_calls)

        assert calls == []


def test_assistant_progress_does_not_persist_metadata_without_visible_text():
    with tempfile.TemporaryDirectory() as d:
        agent = DummyAgent("dummy", memory_file_path=str(Path(d) / "dummy.md"), internal_memory_enabled=False)
        calls = []
        agent._agentpark_persist_assistant_progress = lambda message: calls.append(dict(message))

        agent.AssistantProgress(
            "",
            response_metadata={"protocol": "responses", "response": {"id": "resp-tool"}},
        )

        assert calls == []


def test_provider_turn_metadata_uses_dedicated_callback():
    with tempfile.TemporaryDirectory() as d:
        agent = DummyAgent("dummy", memory_file_path=str(Path(d) / "dummy.md"), internal_memory_enabled=False)
        calls = []
        agent._agentpark_persist_provider_turn_metadata = lambda message: calls.append(dict(message))

        agent.ProviderTurnMetadata(
            tool_calls=[{"id": "call-1", "function": {"name": "read_file"}}],
            response_metadata={"protocol": "responses", "response": {"id": "resp-tool"}},
        )

        assert calls == [{
            "role": "provider_turn",
            "tool_calls": [{"id": "call-1", "function": {"name": "read_file"}}],
            "response_metadata": {"protocol": "responses", "response": {"id": "resp-tool"}},
        }]


def test_messages_with_memory_excludes_progress_and_explicit_exclusions():
    with tempfile.TemporaryDirectory() as d:
        agent = DummyAgent("dummy", memory_file_path=str(Path(d) / "dummy.md"), internal_memory_enabled=False)
        agent.messages = [
            {"role": "user", "content": "question"},
            {"role": "assistant_progress", "content": "working"},
            {"role": "assistant", "content": "hidden", "context_policy": "exclude"},
            {"role": "assistant", "content": "answer"},
        ]

        assert agent._get_messages_with_memory() == [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
