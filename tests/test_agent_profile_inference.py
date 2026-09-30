from tests.agent_invocation_helpers import configured_fake
import json
from pathlib import Path

import pytest

from src import agent_profile_inference as inference
from src.conversation_context.model import ConversationModel, PROMPT
from src.long_term_memory.model import ProfileMemoryModel
from src.providers.agent_runtime_context import get_agent_runtime_context


@pytest.fixture
def profile_runtime(tmp_path, monkeypatch):
    profiles = tmp_path / "agent"
    profiles.mkdir()
    monkeypatch.setattr("src.web_backend.profile_storage.get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(inference.ConfigLoader, "get_provider_config", lambda *_: {
        "model": "default-model", "models": ["default-model", "selected-model"], "supportmode": ["chat"],
    })
    calls = []

    class FakeAgent:
        config = {"apiKey": "test-secret"}

        def __init__(self, provider, **kwargs):
            self.messages = []
            self.options = None
            self.creation = {"provider": provider, **kwargs}
            calls.append(self)
            configured_fake(self, kwargs["agent_config"])

        def Message(self, role, content, **kwargs):
            self.messages.append((role, content))

        def Send(self, **options):
            self.options = options
            return '{"summary":"done"}'

    monkeypatch.setattr(inference, "create_agent", FakeAgent)

    def write(profile_id="custom", **fields):
        path = profiles / f"{profile_id}.json"
        path.write_text(json.dumps({"id": profile_id, "node_type_id": "agent_node", "fields": {
            "provider_id": "test-provider", "model": "selected-model", "thinking": "enabled",
            "reasoning_effort": "medium", "reasoning_summary": "concise",
            "system_prompt": "Preset system", "instruction": "Preset instruction",
            "tools": ["system_tools"], "web_search": "enabled", **fields,
        }}), encoding="utf-8")
        return path

    write()
    return write, calls


def test_conversation_uses_profile_model_reasoning_instructions_and_actual_usage_model(profile_runtime):
    _, calls = profile_runtime
    tracked = []
    model = ConversationModel("custom", graph_id="g", node_id="n",
                              tracker_factory=lambda model_id: tracked.append(model_id))
    assert model.complete('{"history":"synthetic"}') == '{"summary":"done"}'
    agent = calls[0]
    assert agent.creation["provider"] == "test-provider"
    assert agent.creation["model_id"] == "selected-model"
    assert agent.creation["system_prompt"] == "Preset system\n\nPreset instruction\n\n" + PROMPT
    assert agent.creation["internal_memory_enabled"] is False
    assert agent.options == dict(run_tools=False, web_search="disabled", stream=False,
                                 thinking="enabled", reasoning_effort="medium", reasoning_summary="concise", mode="chat", mode_options=None)
    assert tracked == ["selected-model"]
    assert get_agent_runtime_context(agent).responses_instruction == agent.creation["system_prompt"].strip()
    assert not Path(agent.creation["memory_file_path"]).parent.exists()


@pytest.mark.parametrize("phase, expected", [("extract", "low"), ("consolidate", "high"), ("answer", "high")])
def test_memory_phases_use_their_selected_profiles(profile_runtime, phase, expected):
    write, calls = profile_runtime
    write("extract", reasoning_effort="low")
    write("merge", reasoning_effort="high")
    model = ProfileMemoryModel("extract", "merge", graph_id="g", node_id="n")
    model.complete(phase, "Task contract", {"text": "test-secret"})
    agent = calls[0]
    assert agent.options["reasoning_effort"] == expected
    assert agent.creation["model_id"] == "selected-model"
    assert agent.creation["system_prompt"].endswith("Task contract")
    assert "test-secret" not in agent.messages[0][1]
    assert not agent.options["run_tools"]


def test_profile_changes_are_loaded_for_next_call(profile_runtime):
    write, calls = profile_runtime
    model = ConversationModel("custom", graph_id="g", node_id="n")
    model.complete("first")
    write(reasoning_effort="low", thinking="disabled", model="default-model")
    model.complete("second")
    assert calls[1].options["thinking"] == "disabled"
    assert calls[1].options["reasoning_effort"] == "low"
    assert calls[1].creation["model_id"] == "default-model"


@pytest.mark.parametrize("fields", [{"model": "not-allowed"}, {"thinking": []},
                                    {"reasoning_effort": "nonsense"}, {"provider_id": ""}])
def test_invalid_profile_is_not_sent(profile_runtime, fields):
    write, calls = profile_runtime
    write(**fields)
    with pytest.raises(ValueError):
        ConversationModel("custom", graph_id="g", node_id="n").complete("history")
    assert not calls


def test_missing_and_wrong_node_profiles_are_not_sent(profile_runtime):
    write, calls = profile_runtime
    with pytest.raises(ValueError, match="not found"):
        inference.resolve_agent_profile_inference("missing")
    path = write()
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["node_type_id"] = "other"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="agent_node"):
        inference.resolve_agent_profile_inference("custom")
    assert not calls
