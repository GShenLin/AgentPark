import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from nodes.agent_skill_activation import bind_deferred_skills, refresh_skill_messages
from nodes.agent_skill_loader import SkillDefinition
from src.skills.activation_state import load_active_skills
from src.tool.base_tool import BaseTool


def make_agent(path, skills, *, base_tools=()):
    agent = type("Agent", (), {})()
    agent.config = {}
    agent._agentpark_node_directory = str(path)
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.addTool = agent.tools.addTool
    agent.Message = lambda role, content, **kwargs: agent.messages.append({"role": role, "content": content})
    agent.addTool("skill_activation_tools")
    for module in base_tools:
        agent.addTool(module)
    bind_deferred_skills(agent, skills, role="developer")
    return agent


def skill(name, **kwargs):
    return SkillDefinition(name=name, description=name, path=f"skills/{name}/SKILL.md",
                           content=f"Private instructions for {name}.", **kwargs)


def change(agent, name, active=True):
    return json.loads(agent.tools.execute_tool("activate_skill" if active else "deactivate_skill", {"skill": name}))


def test_shared_tools_survive_until_last_owner_closes(tmp_path):
    definitions = [skill(name, tools=("computer_use_tools",)) for name in ("a", "b")]
    agent = make_agent(tmp_path, definitions)
    assert "click" not in agent.tools.function_map
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda name: change(agent, name), ["a", "b"]))
    assert all(r["status"] == "success" for r in results)
    assert load_active_skills(str(tmp_path)) == {"a", "b"}
    assert change(agent, "a", False)["tools_removed"] == []
    assert "click" in agent.tools.function_map
    assert "click" in change(agent, "b", False)["tools_removed"]
    assert "click" not in agent.tools.function_map
    assert change(agent, "b", False)["already_inactive"] is True
    assert "click" not in make_agent(tmp_path, definitions).tools.function_map


def test_explicit_base_tools_survive_skill_deactivation(tmp_path):
    agent = make_agent(tmp_path, [skill("a", tools=("computer_use_tools",))],
                       base_tools=("computer_use_tools",))
    change(agent, "a")
    assert change(agent, "a", False)["tools_removed"] == []
    assert "click" in agent.tools.function_map


def test_shared_mcp_restores_then_retracts_declarations(monkeypatch, tmp_path):
    from nodes import agent_skill_runtime
    calls = []

    def register(target, names, *, settings):
        calls.append(names)
        target.tools.register_external_tool({"type": "function", "function": {
            "name": "mcp__docs__search", "description": "Search", "parameters": {"type": "object"},
        }}, lambda: "ok")

    monkeypatch.setattr(agent_skill_runtime, "register_mcp_server_tools", register)
    definitions = [skill(name, mcp_servers=("docs",)) for name in ("a", "b")]
    agent = make_agent(tmp_path, definitions)
    assert calls == []
    change(agent, "a")
    change(agent, "b")
    assert calls == [["docs"]]
    restored = make_agent(tmp_path, definitions)
    assert "mcp__docs__search" in restored.tools.function_map
    change(restored, "a", False)
    assert "mcp__docs__search" in restored.tools.function_map
    change(restored, "b", False)
    assert "mcp__docs__search" not in restored.tools.function_map


def test_failed_state_save_preserves_current_tools_and_state(monkeypatch, tmp_path):
    from nodes import agent_skill_runtime
    agent = make_agent(tmp_path, [skill("a", tools=("computer_use_tools",))])
    change(agent, "a")

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(agent_skill_runtime, "save_active_skills", fail)
    result = change(agent, "a", False)
    assert result["status"] == "exception"
    assert "click" in agent.tools.function_map
    assert load_active_skills(str(tmp_path)) == {"a"}


def test_current_context_replaces_stale_provider_copy_after_closing(tmp_path):
    agent = make_agent(tmp_path, [skill("a", tools=("computer_use_tools",))])
    change(agent, "a")
    stale = refresh_skill_messages(agent, [], responses=True)
    assert "Private instructions for a" in stale[0]["content"][0]["text"]
    change(agent, "a", False)
    fresh = refresh_skill_messages(agent, stale, responses=True)
    assert len(fresh) == 1
    assert "<state>inactive</state>" in fresh[0]["content"][0]["text"]
    assert "Private instructions for a" not in fresh[0]["content"][0]["text"]


def test_clearing_conversation_resets_activation(tmp_path):
    from src.web_backend.node_memory_store import clear_node_memory
    definitions = [skill("a", tools=("computer_use_tools",))]
    agent = make_agent(tmp_path, definitions)
    change(agent, "a")
    clear_node_memory(str(tmp_path / "memory.md"), str(tmp_path / "messages.jsonl"))
    assert load_active_skills(str(tmp_path)) == set()
    assert "click" not in make_agent(tmp_path, definitions).tools.function_map


def test_removed_skill_is_not_restored_or_resurrected(tmp_path):
    definitions = [skill("a", tools=("computer_use_tools",))]
    change(make_agent(tmp_path, definitions), "a")
    make_agent(tmp_path, [])
    assert load_active_skills(str(tmp_path)) == set()
    assert "click" not in make_agent(tmp_path, definitions).tools.function_map


def test_corrupt_activation_state_is_reported(tmp_path):
    (tmp_path / "agent_skill_state.json").write_text('{"schema_version":1,"active_skills":false}', encoding="utf-8")
    with pytest.raises(ValueError, match="array of skill names"):
        make_agent(tmp_path, [skill("a")])


def test_responses_requests_gain_and_lose_skill_tools_and_instructions(tmp_path):
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.tool_call_protocol import ToolCallExecution

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test", "baseUrl": "https://api.test/v1", "model": "test",
        "responsesApi": True, "maxRetries": 0, "retryDelaySec": 0,
        "responsesReplayReasoningItems": False, "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
    }
    agent.provider_name = "openai"
    agent._agentpark_node_directory = str(tmp_path)
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, **kwargs: agent.messages.append({"role": role, "content": content, **kwargs})
    agent.addTool("skill_activation_tools")
    bind_deferred_skills(agent, [skill("a", tools=("computer_use_tools",))], role="developer")
    payloads = []

    def send(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        index = len(payloads)
        if index <= 2:
            name = "activate_skill" if index == 1 else "deactivate_skill"
            return {"id": f"resp-{index}", "output": [{"type": "function_call", "id": f"fc-{index}",
                    "call_id": f"call-{index}", "name": name, "arguments": '{"skill":"a"}'}]}
        return {"id": "resp-3", "output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}]}

    def execute(_calls):
        index = len(payloads)
        name = "activate_skill" if index == 1 else "deactivate_skill"
        result = agent.tools.execute_tool(name, {"skill": "a"})
        return [ToolCallExecution(func_name=name, call_id=f"call-{index}", cleaned_result=result, images=())]

    agent._post_json_with_retry = send
    agent._stream_responses_with_retry = send
    agent._execute_tool_call_envelopes_parallel = execute
    result = agent._send_via_responses(messages=[{"role": "user", "content": "activate then close"}],
                                     active_tools=list(agent.tool_declarations), run_tools=True)
    assert result == "done"
    assert ["click" in {t["name"] for t in p["tools"]} for p in payloads] == [False, True, False]
    assert ["Private instructions for a" in json.dumps(p["input"]) for p in payloads] == [False, True, False]
