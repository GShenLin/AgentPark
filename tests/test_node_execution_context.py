import os

from src.public_gateway.usage_stats import PublicGatewayUsageStore
from src.web_backend.node_execution_context import bind_node_storage_context


def test_bind_node_storage_context_uses_external_graph_node_directory(tmp_path):
    config_path = tmp_path / "external-memories" / "test" / "GPT" / "config.json"
    context = {"graph_id": "test", "node_instance_id": "GPT"}

    result = bind_node_storage_context(context, str(config_path))

    node_directory = os.path.dirname(os.path.abspath(str(config_path)))
    assert result is context
    assert context["node_config_path"] == os.path.abspath(str(config_path))
    assert context["memory_path"] == os.path.join(node_directory, "memory.md")
    assert context["messages_path"] == os.path.join(node_directory, "messages.jsonl")


def test_agent_node_mid_turn_input_uses_explicit_external_config_path(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module

    captured = {}

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"model": "gpt-test"}

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    def fake_create_agent(*_args, **kwargs):
        captured["create_kwargs"] = kwargs
        return DummyAgent()

    def fake_bind_agent_runtime_context(_agent, runtime_context):
        captured["runtime_context"] = runtime_context

    def fake_consume_mid_turn_user_inputs(config_path):
        captured["consumed_config_path"] = config_path
        return []

    monkeypatch.setattr(
        agent_node_module.ConfigLoader,
        "get_provider_config",
        lambda _loader, _provider_id: {"supportmode": ["chat"]},
    )
    monkeypatch.setattr(agent_node_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(agent_node_module, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(agent_node_module, "bind_agent_runtime_context", fake_bind_agent_runtime_context)
    monkeypatch.setattr(
        agent_node_module,
        "_consume_node_mid_turn_user_inputs",
        fake_consume_mid_turn_user_inputs,
    )

    node_dir = tmp_path / "external-memories" / "test" / "GPT"
    node_dir.mkdir(parents=True)
    config_path = node_dir / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    memory_path = node_dir / "memory.md"
    messages_path = node_dir / "messages.jsonl"

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "test",
            "node_instance_id": "GPT",
            "provider_id": "provider-stream",
            "node_config_path": str(config_path),
            "memory_path": str(memory_path),
            "messages_path": str(messages_path),
            "access_ip": "127.0.0.1",
        },
    )
    captured["runtime_context"].consume_mid_turn_user_inputs()

    assert str(result.get("display") or "") == "ok"
    assert captured["create_kwargs"]["memory_file_path"] == str(memory_path)
    assert captured["consumed_config_path"] == str(config_path)
    assert captured["runtime_context"].client_ip == "127.0.0.1"
    tracker = captured["runtime_context"].provider_request_tracker
    tracker.record_summary({"request_index": 1, "request_api": "responses"})
    tracker.record_completion(1, {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
    usage_file = next((tmp_path / ".runtime" / "public-gateway-usage").glob("*.jsonl"))
    stats = PublicGatewayUsageStore(str(tmp_path)).aggregate(usage_file.stem)
    assert stats["ips"][0]["models"][0]["totalTokens"] == 5
