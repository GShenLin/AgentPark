import time

import pytest


def test_agent_node_stream_callback_and_done(monkeypatch):
    import nodes.agent_node as agent_node_module

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            handler = kwargs.get("stream_handler")
            if callable(handler):
                handler("A", "A")
                handler("B", "AB")
            return "AB"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    streamed_events: list[dict] = []

    result = node.on_input(
        "hello",
        {
            "graph_id": "g_stream_unit",
            "node_instance_id": "n_stream_unit",
            "provider_id": "provider-stream",
            "stream_callback": lambda payload: streamed_events.append(dict(payload)),
        },
    )

    assert isinstance(result, dict)
    assert str(result.get("display") or "") == "AB"

    assert streamed_events, "stream callback should receive message delta and done events"
    assert any(str(item.get("type") or "") == "node_message_delta" for item in streamed_events)
    assert any(str(item.get("type") or "") == "node_message_done" for item in streamed_events)
    done_event = next((item for item in streamed_events if str(item.get("type") or "") == "node_message_done"), None)
    assert isinstance(done_event, dict)
    assert str(done_event.get("text") or "") == "AB"


def test_agent_node_forwards_tool_lifecycle_events(monkeypatch):
    import nodes.agent_node as agent_node_module

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tool_event_callback = None

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            assert callable(self.tool_event_callback)
            self.tool_event_callback(
                {
                    "type": "tool_call_start",
                    "name": "read_file",
                    "call_id": "call-1",
                    "provider": "unit",
                    "arguments": {"filePath": "README.md"},
                }
            )
            self.tool_event_callback(
                {
                    "type": "tool_call_end",
                    "name": "read_file",
                    "call_id": "call-1",
                    "provider": "unit",
                    "status": "completed",
                    "duration_ms": 3,
                    "result_preview": "ok",
                }
            )
            return "done"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    events: list[dict] = []
    node = agent_node_module.Node()

    result = node.on_input(
        "hello",
        {
            "graph_id": "g_tool_event_unit",
            "node_instance_id": "n_tool_event_unit",
            "provider_id": "provider-stream",
            "stream_callback": lambda payload: events.append(dict(payload)),
        },
    )

    assert str(result.get("display") or "") == "done"
    event_types = [str(item.get("type") or "") for item in events]
    assert "tool_call_start" in event_types
    assert "tool_call_end" in event_types
    assert events[event_types.index("tool_call_start")]["name"] == "read_file"
    assert events[event_types.index("tool_call_end")]["status"] == "completed"


def test_agent_node_injects_working_path_prompt(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    result = node.on_input(
        "hello",
        {
            "graph_id": "g_working_path_unit",
            "node_instance_id": "n_working_path_unit",
            "provider_id": "provider-stream",
            "working_path": r"C:\Project\AITools\XYJ",
        },
    )

    assert str(result.get("display") or "") == "ok"
    sent_user = next(item for item in created_agents[0].messages if item.get("role") == "user")
    content = str(sent_user.get("content") or "")
    assert "节点工作路径: C:\\Project\\AITools\\XYJ" in content
    assert "hello" in content


def test_agent_node_surfaces_configured_tool_load_failure(monkeypatch):
    import nodes.agent_node as agent_node_module
    from src.tool_load_errors import ToolLoadError

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, name):
            raise ToolLoadError(f"bad tool: {name}")

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            raise AssertionError("Send should not run when configured tools fail to load")

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    with pytest.raises(RuntimeError) as exc:
        node.on_input(
            "hello",
            {
                "graph_id": "g_bad_tool_unit",
                "node_instance_id": "n_bad_tool_unit",
                "provider_id": "provider-stream",
                "tools": ["missing_tool"],
            },
        )

    assert "Configured tools failed to load" in str(exc.value)
    assert "bad tool: missing_tool" in str(exc.value)


def test_agent_node_prepends_working_path_to_multimodal_content():
    from nodes.agent_working_path_context import prepend_working_path_context

    content = [
        {"type": "text", "text": "describe image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]

    updated = prepend_working_path_context(content, r"C:\Project\AITools")

    assert isinstance(updated, list)
    assert updated[0]["type"] == "text"
    assert "节点工作路径: C:\\Project\\AITools" in updated[0]["text"]
    assert "describe image" in updated[0]["text"]
    assert updated[1] == content[1]


def test_graph_runner_updates_last_message_during_stream(monkeypatch, tmp_path):
    import src.web_backend as backend
    import nodes.agent_node as agent_node_module
    import src.providers as providers_module
    import src.web_backend.runtime_paths as runtime_paths_module
    import src.web_backend.node_runtime as node_runtime_module

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    original_runtime_paths_get_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_get_resource_root = runtime_paths_module._get_resource_root
    original_node_runtime_get_runtime_root = node_runtime_module._get_runtime_root
    original_node_runtime_get_resource_root = node_runtime_module._get_resource_root
    resource_root = original_get_runtime_root()

    class SlowStreamingAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            handler = kwargs.get("stream_handler")
            if callable(handler):
                handler("H", "H")
                time.sleep(0.2)
            if callable(getattr(self, "tool_event_callback", None)):
                self.tool_event_callback(
                    {
                        "type": "tool_call_start",
                        "name": "read_file",
                        "call_id": "call-1",
                        "provider": "unit",
                        "arguments": {"filePath": "README.md"},
                    }
                )
                time.sleep(0.05)
                self.tool_event_callback(
                    {
                        "type": "tool_call_end",
                        "name": "read_file",
                        "call_id": "call-1",
                        "provider": "unit",
                        "status": "completed",
                        "duration_ms": 2,
                        "result_preview": "ok",
                    }
                )
                time.sleep(0.05)
            if callable(handler):
                handler("i", "Hi")
            time.sleep(0.1)
            return "Hi"

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    node_runtime_module._get_runtime_root = lambda: runtime_root
    node_runtime_module._get_resource_root = lambda: resource_root
    monkeypatch.setattr(providers_module, "create_agent", lambda *_args, **_kwargs: SlowStreamingAgent())
    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: SlowStreamingAgent())

    try:
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {"id": "default", "name": "default", "links": []}
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        assert (
            client.post(
                "/api/nodes/instances",
                json={"node_id": "agent1", "type_id": "agent_node", "graph_id": "default"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/nodes/instances/agent1/config?graph_id=default",
                json={"fields": {"provider_id": "doubao-2.0-pro"}},
            ).status_code
            == 200
        )
        assert client.post("/api/graphs/default/runner/start").status_code == 200
        assert client.post("/api/graphs/default/emit", json={"from_id": "agent1", "payload": "hello"}).status_code == 200

        saw_partial = False
        saw_tool_event = False
        saw_tool_event_without_message_override = False
        saw_runtime_history = False
        saw_runtime_tool_call = False
        saw_runtime_event_cleared = False
        saw_final = False
        for _ in range(80):
            cfgs = client.get("/api/nodes/instances/configs?graph_id=default")
            assert cfgs.status_code == 200
            nodes = cfgs.json().get("nodes") or []
            cfg = next((item for item in nodes if str(item.get("node_id") or "") == "agent1"), None)
            if not isinstance(cfg, dict):
                time.sleep(0.05)
                continue
            state = str(cfg.get("state") or "idle")
            last_message = str(cfg.get("last_message") or "")
            if state == "working" and last_message == "H":
                saw_partial = True
            last_runtime_event = cfg.get("last_runtime_event")
            if isinstance(last_runtime_event, dict) and last_runtime_event.get("name") == "read_file":
                saw_tool_event = True
                if state == "working" and last_message == "H":
                    saw_tool_event_without_message_override = True
            runtime_events = cfg.get("runtime_events")
            if isinstance(runtime_events, list) and len(runtime_events) >= 2:
                names = [item.get("name") for item in runtime_events if isinstance(item, dict)]
                types = [item.get("type") for item in runtime_events if isinstance(item, dict)]
                if "read_file" in names and "tool_call_start" in types and "tool_call_end" in types:
                    saw_runtime_history = True
            runtime_tool_calls = cfg.get("runtime_tool_calls")
            if isinstance(runtime_tool_calls, list):
                call = next((item for item in runtime_tool_calls if isinstance(item, dict) and item.get("call_id") == "call-1"), None)
                if isinstance(call, dict) and call.get("name") == "read_file" and call.get("status") == "completed":
                    saw_runtime_tool_call = True
            if str(cfg.get("last_run_at") or "").strip() and last_message == "Hi":
                saw_runtime_event_cleared = cfg.get("last_runtime_event") is None
                runtime_events = cfg.get("runtime_events")
                if isinstance(runtime_events, list) and len(runtime_events) >= 2:
                    saw_runtime_history = True
                runtime_tool_calls = cfg.get("runtime_tool_calls")
                if isinstance(runtime_tool_calls, list):
                    call = next((item for item in runtime_tool_calls if isinstance(item, dict) and item.get("call_id") == "call-1"), None)
                    if isinstance(call, dict) and call.get("name") == "read_file" and call.get("status") == "completed":
                        saw_runtime_tool_call = True
                saw_final = True
                break
            time.sleep(0.05)

        assert saw_partial, "expected partial stream text in last_message while node is working"
        assert saw_tool_event, "expected structured tool lifecycle event in node config"
        assert saw_tool_event_without_message_override, "expected tool lifecycle event to preserve streamed assistant text"
        assert saw_runtime_history, "expected bounded tool lifecycle history in node config"
        assert saw_runtime_tool_call, "expected grouped runtime tool call item in node config"
        assert saw_runtime_event_cleared, "expected tool lifecycle event to clear after final output"
        assert saw_final, "expected final message and last_run_at after completion"

        mem = client.get("/api/nodes/instances/agent1/memory?graph_id=default&max_chars=20000")
        assert mem.status_code == 200
        body = mem.json() or {}
        messages = body.get("messages") or []
        assert any(str(item.get("role") or "") == "assistant" for item in messages if isinstance(item, dict))
        tool_messages = [item for item in messages if isinstance(item, dict) and str(item.get("role") or "") == "tool"]
        assert tool_messages, "expected tool lifecycle item persisted in node message history"
        tool_parts = [part for item in tool_messages for part in (item.get("parts") or []) if isinstance(part, dict)]
        tool_part = next((part for part in tool_parts if part.get("type") == "tool_call" and part.get("call_id") == "call-1"), None)
        assert isinstance(tool_part, dict)
        assert tool_part.get("name") == "read_file"
        assert tool_part.get("status") == "completed"
        assert tool_part.get("result_preview") == "ok"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_get_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_get_resource_root
        node_runtime_module._get_runtime_root = original_node_runtime_get_runtime_root
        node_runtime_module._get_resource_root = original_node_runtime_get_resource_root
