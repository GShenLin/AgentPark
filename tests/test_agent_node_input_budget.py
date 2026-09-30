from tests.agent_invocation_helpers import configured_fake
import base64
import json

import pytest

from src.conversation_context.window import CHECKPOINT_PREFIX


@pytest.mark.parametrize("history_count", [0, 30])
@pytest.mark.parametrize("input_kind", ["text", "image", "instructions_and_tools"])
def test_large_current_request_reaches_send_without_front_compaction(
    monkeypatch, tmp_path, history_count, input_kind,
):
    import nodes.agent_node as module

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tool_declarations = []
            if input_kind == "instructions_and_tools":
                self.tool_declarations = [{"name": "large_tool", "description": "t" * 120_000}]
                self.messages.append({"role": "system", "content": "i" * 120_000})
            self.sent = False

        def addTool(self, _name):
            pass

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, **kwargs})

        def Send(self, **kwargs):
            self.sent = True
            return "sent"

    agent = DummyAgent()
    monkeypatch.setattr(module, "create_agent", lambda *args, **kwargs: configured_fake(agent, kwargs.get("agent_config")))
    monkeypatch.setattr(module.ConfigLoader, "get_provider_config", lambda *args: {"supportmode": ["chat"]})
    monkeypatch.setattr(module, "_workspace_config", lambda: {
        "agentNode": {"minSendDelayMs": 0},
        "conversationContext": {"input_tokens": 4096, "retain_tokens": 800, "summary_tokens": 500},
    })
    summaries = []

    def complete(_self, payload):
        summaries.append(json.loads(payload))
        return '{"summary":"Earlier conversation constraints"}'

    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", complete)
    context = {
        "graph_id": "input-budget-test", "node_instance_id": "node", "provider_id": "test-chat",
        "memory_path": str(tmp_path / "memory.md"),
        "messages_path": str(tmp_path / "messages.jsonl"),
    }
    node = module.Node()
    history_path = tmp_path / "messages.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    records = [{"id": f"old-{i}", "role": "user" if i % 2 == 0 else "assistant",
                "parts": [{"type": "text", "text": f"old-{i}: " + "h" * 1200}]}
               for i in range(history_count)]
    parts = [{"type": "text", "text": "x" * 120_000 if input_kind == "text" else "inspect"}]
    expected_input = parts[0]["text"]
    if input_kind == "image":
        image_bytes = b"\xff\xd8\xff" + b"x" * 739_506
        image_path = tmp_path / "screenshot.jpg"
        image_path.write_bytes(image_bytes)
        parts.append({"type": "resource", "resource": {
            "id": "image", "uri": str(image_path), "kind": "image", "mime": "image/jpeg",
        }})
        expected_input = [
            {"type": "text", "text": "inspect"},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii"),
            }},
        ]
    current = {"id": "current", "role": "user", "parts": parts}
    history_path.write_text("".join(json.dumps(r) + "\n" for r in [*records, current]), encoding="utf-8")
    original = history_path.read_bytes()

    result = node.on_input(current, context)

    assert agent.sent
    assert result["display"] == "sent"
    assert agent.messages[-1]["content"] == expected_input
    assert history_path.read_bytes() == original
    assert not summaries
    if history_count:
        assert not any(str(m["content"]).startswith(CHECKPOINT_PREFIX) for m in agent.messages)
        assert any(m["content"] == records[0]["parts"][0]["text"] for m in agent.messages)
        assert agent.messages[-2]["content"] == records[-1]["parts"][0]["text"]
