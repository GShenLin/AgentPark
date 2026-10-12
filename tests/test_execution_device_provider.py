"""Exercise switching through the real Responses continuation and streaming path."""
import json

import pytest

from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.remote_workspace.device_state import device_state
from tests.test_responses_item_runtime import _openai_agent, _emit_item_events


@pytest.mark.parametrize("mixed", [False, True])
def test_streamed_switch_waits_for_batch_and_refreshes_next_request(tmp_path, mixed):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "AGENTS.md").write_text("Instructions for old device A.", encoding="utf-8")
    (b / "AGENTS.md").write_text("Instructions for target device B.", encoding="utf-8")
    agent = _openai_agent()
    bind_agent_runtime_context(agent, AgentRuntimeContext(working_path=str(a)))
    agent.tools.addTool("execution_device_tools")
    agent.tools.addTool("file_write_tools")
    payloads = []
    calls = [{"type": "function_call", "id": "fc-switch", "call_id": "switch", "name": "switch_execution_device",
              "arguments": json.dumps({"device_id": "local", "working_path": str(b), "expected_revision": 0})}]
    if mixed:
        calls.insert(0, {"type": "function_call", "id": "fc-write", "call_id": "write", "name": "write_file",
                         "arguments": json.dumps({"file_path": "must-not-exist.txt", "content": "unsafe"})})
    def stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        if len(payloads) == 1:
            for call in calls:
                _emit_item_events(kwargs["item_event_handler"], [
                    {"type": "response.output_item.added", "item": {"type": "function_call", "id": call["id"], "name": call["name"]}},
                    {"type": "response.output_item.done", "item": call},
                ])
                assert device_state(agent).revision == 0
                assert not (a / "must-not-exist.txt").exists()
            return {"id": "response-tools", "output": calls}
        return {"id": "response-final", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "done"}]},
        ]}
    agent._stream_responses_with_retry = stream
    result = agent._send_via_responses(
        messages=[{"role": "user", "content": "Switch workspaces."}],
        active_tools=agent.tool_declarations, run_tools=True, reasoning_effort="",
    )
    assert result == "done" and len(payloads) == 2
    text = json.dumps(payloads[1])
    if mixed:
        assert device_state(agent).revision == 0
        assert "must be called alone" in text
        assert not (a / "must-not-exist.txt").exists() and not (b / "must-not-exist.txt").exists()
    else:
        assert device_state(agent).revision == 1
        assert "<execution_workspace_update>" in text
        assert "Instructions for target device B." in text
        assert "Instructions for old device A." not in text


def test_chat_context_survives_memory_tail_selection(tmp_path):
    from types import SimpleNamespace
    from src.providers.provider_message_policy import ProviderMessagePolicyMixin
    from src.remote_workspace.device_tools import switch_execution_device
    class Agent(ProviderMessagePolicyMixin):
        pass
    agent = Agent()
    agent.config = {}
    agent.internal_memory_enabled = True
    agent.messages = [{"role": "user", "content": "Original task"}]
    agent.memory = SimpleNamespace(build_messages_with_memory=lambda messages: messages)
    bind_agent_runtime_context(agent, AgentRuntimeContext(working_path=str(tmp_path)))
    switch_execution_device("local", str(tmp_path), 0, agent=agent)
    messages = agent._get_messages_with_memory()
    assert any("<execution_workspace_update>" in m["content"] for m in messages)
    assert any(m["content"] == "Original task" for m in messages)
