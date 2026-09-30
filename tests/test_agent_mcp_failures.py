"""MCP failures must reach the model without aborting an agent turn."""
import json
from types import SimpleNamespace

import httpx
import pytest

from nodes.agent_mcp_loader import McpServerDefinition, register_mcp_server_tools
from nodes.agent_skill_activation import bind_deferred_skills
from nodes.agent_skill_loader import SkillDefinition
from src.runtime_cancellation import CancellationRequested
from src.skills.activation_state import load_active_skills, save_active_skills
from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallEnvelope


SETTINGS = {"mcpServers": {"unreal-mcp": {"transport": "sse", "url": "http://example.test/sse"}}}


def make_agent(tmp_path):
    agent = SimpleNamespace(config={}, messages=[], _agentpark_node_directory=str(tmp_path))
    agent.tools = BaseTool(agent)
    agent.addTool = agent.tools.addTool
    agent.Message = lambda role, content, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs})
    return agent


def connection_error():
    return ExceptionGroup("unhandled errors in a TaskGroup", [
        httpx.ConnectError("All connection attempts failed")])


class Client:
    offline = False
    call_error = False

    def __init__(self, server):
        self.server = server

    def list_tools(self):
        if self.offline:
            raise connection_error()
        return [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]

    def call_tool(self, name, arguments):
        if self.call_error:
            raise connection_error()
        return "ok"


@pytest.fixture
def client(monkeypatch):
    import nodes.agent_mcp_runtime as runtime
    monkeypatch.setattr(runtime, "McpServerClient", Client)
    monkeypatch.setattr(Client, "offline", False)
    monkeypatch.setattr(Client, "call_error", False)
    return Client


def test_restore_mcp_failure_keeps_other_skills_and_can_retry(tmp_path, client):
    definitions = [
        SkillDefinition(name="unreal", description="Unreal", path="unreal/SKILL.md",
                        content="Unreal instructions", mcp_servers=("unreal-mcp",)),
        SkillDefinition(name="local", description="Local", path="local/SKILL.md", content="Local instructions"),
    ]
    save_active_skills(str(tmp_path), {"unreal", "local"})
    client.offline = True
    agent = make_agent(tmp_path)
    agent.addTool("skill_activation_tools")
    bind_deferred_skills(agent, definitions, role="developer", mcp_settings=SETTINGS)

    assert agent._agentpark_skill_runtime.active == {"local"}
    assert load_active_skills(str(tmp_path)) == {"unreal", "local"}
    failures = [json.loads(m["content"]) for m in agent.messages if m["content"].startswith('{')]
    assert failures[0]["phase"] == "restore_skill"
    assert failures[0]["skill"] == "unreal"
    assert "ConnectError: All connection attempts failed" in failures[0]["error"]
    assert "mcp__unreal-mcp__echo" not in agent.tools.function_map

    failed = agent.tools.execute_tool_result("activate_skill", {"skill": "unreal"})
    assert not failed.ok
    assert "All connection attempts failed" in failed.model_output()
    assert agent._agentpark_skill_runtime.active == {"local"}
    client.offline = False
    success = agent.tools.execute_tool_result("activate_skill", {"skill": "unreal"})
    assert success.ok
    assert "mcp__unreal-mcp__echo" in agent.tools.function_map


def test_call_failure_retains_root_cause_and_call_id(tmp_path, client):
    agent = make_agent(tmp_path)
    register_mcp_server_tools(agent, ["unreal-mcp"], settings=SETTINGS)
    client.call_error = True
    name = "mcp__unreal-mcp__echo"
    result = agent.tools.execute_tool_call(ToolCallEnvelope(
        name=name, call_id="mcp-call-1", arguments={}, arguments_json="{}", provider="test"))
    payload = json.loads(result.cleaned_result)
    assert result.call_id == "mcp-call-1"
    assert result.status == "exception"
    assert payload["server"] == "unreal-mcp"
    assert payload["error"] == "ConnectError: All connection attempts failed"
    client.call_error = False
    assert agent.tools.execute_tool_result(name, {}).ok


def test_oversize_mcp_error_remains_an_error(tmp_path, monkeypatch, client):
    from nodes.agent_mcp_results import normalize_mcp_call_result
    message = "MCP operation failed: " + "x" * 1000
    remote_result = normalize_mcp_call_result(SimpleNamespace(
        content=[{"type": "text", "text": message}], isError=True))
    monkeypatch.setattr(Client, "call_tool", lambda *args: remote_result)
    agent = make_agent(tmp_path)
    settings = {"mcpServers": {"unreal-mcp": {**SETTINGS["mcpServers"]["unreal-mcp"], "toolResultMaxChars": 100}}}
    register_mcp_server_tools(agent, ["unreal-mcp"], settings=settings)
    result = agent.tools.execute_tool_result("mcp__unreal-mcp__echo", {})
    assert not result.ok
    assert result.error == message
    assert json.loads(result.model_output())["status"] == "error"


def test_discovery_cancellation_is_not_an_mcp_load_failure(monkeypatch, client):
    import nodes.agent_mcp_runtime as runtime

    def cancelled(_self):
        raise CancellationRequested("Operation cancelled.")

    monkeypatch.setattr(Client, "list_tools", cancelled)
    with pytest.raises(CancellationRequested):
        runtime.materialize_mcp_server_tools([
            McpServerDefinition(name="unreal-mcp", label="Unreal", config=SETTINGS["mcpServers"]["unreal-mcp"])])


def test_responses_loop_receives_mcp_error_and_completes(tmp_path, client):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test", "baseUrl": "https://api.test/v1", "model": "test",
        "responsesApi": True, "maxRetries": 0, "retryDelaySec": 0,
        "responsesReplayReasoningItems": False, "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
    }
    agent.provider_name = "openai"
    agent.internal_memory_enabled = False
    agent._agentpark_node_directory = str(tmp_path)
    agent.messages = []
    agent.tools = BaseTool(agent)
    register_mcp_server_tools(agent, ["unreal-mcp"], settings=SETTINGS)
    client.call_error = True
    payloads = []

    def send(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        if len(payloads) == 1:
            return {"id": "resp-1", "output": [{"type": "function_call", "id": "fc-1",
                    "call_id": "call-1", "name": "mcp__unreal-mcp__echo", "arguments": "{}"}]}
        outputs = [item for item in payload["input"] if item.get("type") == "function_call_output"]
        assert outputs[0]["call_id"] == "call-1"
        assert "ConnectError: All connection attempts failed" in outputs[0]["output"]
        assert json.loads(outputs[0]["output"])["status"] == "exception"
        return {"id": "resp-2", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "MCP failed; continuing with the available information."}]}]}

    agent._post_json_with_retry = send
    agent._stream_responses_with_retry = send
    agent._execute_tool_call_envelopes_parallel = lambda calls: [agent.tools.execute_tool_call(call) for call in calls]
    result = agent._send_via_responses(messages=[{"role": "user", "content": "Use Unreal"}],
                                     active_tools=list(agent.tool_declarations), run_tools=True)
    assert len(payloads) == 2
    assert result == "MCP failed; continuing with the available information."
