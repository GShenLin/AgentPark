"""Exercise the factory and real Send bodies behind isolated transport boundaries."""
import json
from pathlib import Path

import pytest

from src.agent_profile_inference import resolve_agent_profile_inference
from src.conversation_context.model import ConversationModel
from src.long_term_memory.model import ProfileMemoryModel
from src.providers import registry
from src.providers.agent_config import AgentConfig, AgentSendContext
from src.providers.agent_invocation import send_agent


@pytest.fixture
def profile_provider(monkeypatch, tmp_path):
    profiles = tmp_path / "agent"
    profiles.mkdir()
    monkeypatch.setattr("src.web_backend.profile_storage.get_workspace_root", lambda: str(tmp_path))
    calls = []

    def configure(kind="doubao", model="test-model"):
        settings = {"type": kind, "responsesApi": True, "model": model, "models": [model],
                    "supportmode": ["chat"], "apiKey": "test"}
        monkeypatch.setattr(registry.ConfigLoader, "get_provider_config", lambda *_: dict(settings))
        cls = registry.PROVIDER_REGISTRATIONS[kind].load_class()

        def transport(self, **kwargs):
            calls.append((self, kwargs))
            return '{"summary":"synthetic result"}'

        monkeypatch.setattr(cls, "_send_via_responses", transport, raising=False)
        for profile_id in ("extract", "consolidate"):
            (profiles / f"{profile_id}.json").write_text(json.dumps({
                "id": profile_id, "node_type_id": "agent_node", "fields": {
                    "provider_id": "test-provider", "model": model,
                    "system_prompt": "Preset system", "instruction": "Preset instruction",
                    "thinking": "enabled", "reasoning_effort": "high", "reasoning_summary": "detailed",
                    "tools": ["system_tools"], "web_search": "enabled",
                },
            }), encoding="utf-8")
        return calls

    return configure


@pytest.mark.parametrize("kind", ["doubao", "openai", "deepseek", "grok", "agnes"])
@pytest.mark.parametrize("phase", ["conversation", "extract", "consolidate", "answer"])
def test_internal_profile_paths_execute_real_send_without_foreign_parameters(profile_provider, kind, phase):
    calls = profile_provider(kind)
    if phase == "conversation":
        result = ConversationModel("extract", graph_id="g", node_id="n").complete("synthetic history")
    else:
        result = ProfileMemoryModel("extract", "consolidate", graph_id="g", node_id="n").complete(
            phase, "Task-specific contract", {"text": "synthetic history"})
    assert json.loads(result) == {"summary": "synthetic result"}
    assert len(calls) == 1
    agent, sent = calls[0]
    assert sent["run_tools"] is False
    assert sent["web_search_mode"] == "disabled"
    assert sent["stream_handler"] is None
    assert sent["thinking_stream_handler"] is None
    assert agent.config["model"] == "test-model"
    assert agent.system_prompt.startswith("Preset system\n\nPreset instruction")
    if kind in {"doubao", "grok"}:
        assert "reasoning_summary" not in agent._agent_invocation.send_kwargs
    else:
        assert sent["reasoning_summary"] == "detailed"


def test_switching_profile_provider_recompiles_contract(profile_provider):
    model = ConversationModel("extract", graph_id="g", node_id="n")
    calls = profile_provider("openai", "gpt-test")
    model.complete("first")
    assert calls[-1][0]._agent_invocation.send_kwargs["reasoning_summary"] == "detailed"
    profile_provider("doubao", "doubao-test")
    model.complete("second")
    assert calls[-1][0].selected_model_id == "doubao-test"
    assert "reasoning_summary" not in calls[-1][0]._agent_invocation.send_kwargs


def test_actual_doubao_empty_summary_regression(profile_provider):
    profile_provider("doubao")
    profile = resolve_agent_profile_inference("extract")
    from dataclasses import replace
    profile = replace(profile, reasoning_summary="")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        agent = profile.create_agent(str(Path(folder) / "memory.md"), "Return JSON")
        agent.Message("user", "synthetic", persist=False)
        assert json.loads(send_agent(agent))["summary"] == "synthetic result"
        assert "reasoning_summary" not in agent._agent_invocation.send_kwargs


def test_normal_node_uses_factory_mapping_and_real_doubao_send(profile_provider, monkeypatch, tmp_path):
    import nodes.agent_node as node
    calls = profile_provider("doubao")
    monkeypatch.setattr(node, "_workspace_config", lambda: {})
    result = node.Node().on_input("synthetic input", {
        "provider_id": "test-provider", "graph_id": "g", "node_instance_id": "n",
        "memory_path": str(tmp_path / "node" / "memory.md"),
        "messages_path": str(tmp_path / "node" / "messages.jsonl"),
        "tools": [], "skills": [], "mcp_servers": [], "plugins": [],
        "reasoning_summary": "concise", "thinking": "enabled", "reasoning_effort": "high",
    })
    assert "synthetic result" in result["display"]
    agent, sent = calls[0]
    assert sent["run_tools"] is True
    assert callable(sent["stream_handler"])
    assert callable(sent["thinking_stream_handler"])
    assert "reasoning_summary" not in agent._agent_invocation.send_kwargs


def test_other_application_sends_share_compiled_configuration(profile_provider, tmp_path):
    from src.base_agent_manager import BaseAgentManager
    calls = profile_provider("doubao")
    agent = registry.create_agent("test", memory_file_path=str(tmp_path / "memory.md"),
                                  internal_memory_enabled=False,
                                  agent_config=AgentConfig(run_tools=False, reasoning_summary="concise"))
    agent.send()
    BaseAgentManager(agent)._send_with_optional_kwargs(run_tools=False)
    agent.tools._send_with_optional_kwargs(run_tools=False)
    assert len(calls) == 3
    assert all(sent["run_tools"] is False for _, sent in calls)
    send_agent(agent, AgentSendContext(run_tools=True))
    assert calls[-1][1]["run_tools"] is True
    agent.send()
    assert calls[-1][1]["run_tools"] is False


def test_goal_evaluator_uses_compiled_doubao_configuration(profile_provider, monkeypatch):
    from src.web_backend.node_goal_runtime import NodeGoalRuntime
    calls = profile_provider("doubao")
    cls = registry.PROVIDER_REGISTRATIONS["doubao"].load_class()

    def transport(self, **kwargs):
        calls.append((self, kwargs))
        return '{"new_goal_state":"active","reason":"unfinished"}'

    monkeypatch.setattr(cls, "_send_via_responses", transport)
    evaluator = NodeGoalRuntime(object())
    result = evaluator._run_goal_evaluator(
        provider_id="test", config={"reasoning_effort": "high"}, goal="synthetic goal", state={},
        input_message={"role": "user", "parts": [{"type": "text", "text": "synthetic input"}]},
        output_message={"role": "assistant", "parts": [{"type": "text", "text": "unfinished"}]},
    )
    assert result["new_goal_state"] == "active"
    assert calls[0][1]["run_tools"] is False
    assert calls[0][1]["thinking_mode"] == "disabled"


def test_planner_decisions_and_summaries_share_mapping(profile_provider, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from src.leader_decision_engine import LeaderDecisionEngine
    from src.plan_result_summarizer import PlanResultSummarizer
    calls = profile_provider("doubao")
    agent = registry.create_agent("test", memory_file_path=str(tmp_path / "plan.md"),
                                  internal_memory_enabled=False,
                                  agent_config=AgentConfig(reasoning_summary="detailed"))
    agent.Message("user", "preserved", persist=False)
    engine = LeaderDecisionEngine(agent, SimpleNamespace(parse_first_json_object=lambda _: {"status": "done"}))
    engine.decide_next("task", {"name": "worker"}, "output", {}, [])
    engine.decide_batch("task", {}, {}, [])
    assert "synthetic result" in PlanResultSummarizer(agent).summarize("task", {})
    assert len(calls) == 3
    assert all(sent["run_tools"] is False for _, sent in calls)
    assert agent.messages[0]["content"] == "preserved"
