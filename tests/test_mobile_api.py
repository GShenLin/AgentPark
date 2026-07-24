import json
import os
import shutil


def test_mobile_api_lists_current_pc_graphs_nodes_and_sends_message(monkeypatch, tmp_path):
    import src.web_backend as backend
    import src.web_backend.mobile_api as mobile_api_module
    import src.web_backend.node_runtime as node_runtime_module
    import src.web_backend.runtime_paths as runtime_paths_module
    from src.web_backend.state_store import _set_node_config_runtime_event

    runtime_root = str(tmp_path / "AgentPark")
    resource_root = backend._get_runtime_root()
    os.makedirs(runtime_root, exist_ok=True)

    original_backend_runtime_root = backend._get_runtime_root
    original_backend_resource_root = backend._get_resource_root
    original_runtime_paths_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_resource_root = runtime_paths_module._get_resource_root
    original_node_runtime_runtime_root = node_runtime_module._get_runtime_root
    original_node_runtime_resource_root = node_runtime_module._get_resource_root
    original_mobile_runtime_root = mobile_api_module._get_runtime_root
    graph_runtime = None
    original_ensure = None
    original_wake = None

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    node_runtime_module._get_runtime_root = lambda: runtime_root
    node_runtime_module._get_resource_root = lambda: resource_root
    mobile_api_module._get_runtime_root = lambda: runtime_root

    try:
        facade = backend.WebBackendFacade()
        app = facade.build()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {"id": "default", "name": "Default", "output_routes": {}}
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        create_node = client.post(
            "/api/nodes/instances",
            json={"node_id": "agent1", "type_id": "agent_node", "name": "Agent 1", "graph_id": "default"},
        )
        assert create_node.status_code == 200

        graph_runtime = facade.core.graph_runtime
        ensure_calls: list[str] = []
        wake_calls: list[str] = []
        original_ensure = graph_runtime._ensure_graph_runner
        original_wake = graph_runtime._wake_graph_runner
        graph_runtime._ensure_graph_runner = lambda graph_id: ensure_calls.append(graph_id)
        graph_runtime._wake_graph_runner = lambda graph_id: wake_calls.append(graph_id)

        pcs = client.get("/api/mobile/pcs")
        assert pcs.status_code == 200
        assert pcs.json()["pcs"][0]["id"] == "local"
        assert pcs.json()["pcs"][0]["instances"][0]["name"] == "AgentPark"

        graphs = client.get("/api/mobile/pcs/local/graphs")
        assert graphs.status_code == 200
        graph_item = graphs.json()["instances"][0]["graphs"][0]
        assert graph_item["id"] == "default"
        assert graph_item["display_name"] == "AgentPark.Default"

        nodes = client.get("/api/mobile/pcs/local/graphs/default/nodes")
        assert nodes.status_code == 200
        assert nodes.json()["nodes"][0]["id"] == "agent1"

        config_path = facade.core.graph_runtime._node_config_path("agent1", "default")
        _set_node_config_runtime_event(
            config_path,
            {
                "type": "tool_call_start",
                "name": "read_file",
                "call_id": "call-1",
                "provider": "unit",
                "arguments": {"filePath": "README.md"},
            },
        )
        nodes_with_tool = client.get("/api/mobile/pcs/local/graphs/default/nodes")
        assert nodes_with_tool.status_code == 200
        mobile_node = nodes_with_tool.json()["nodes"][0]
        assert mobile_node["last_runtime_event"]["type"] == "tool_call_start"
        assert mobile_node["runtime_tool_calls"][0]["call_id"] == "call-1"
        assert mobile_node["runtime_tool_calls"][0]["status"] == "running"

        sent = client.post(
            "/api/mobile/pcs/local/graphs/default/nodes/agent1/messages",
            json={"message": "hello from phone"},
        )
        assert sent.status_code == 200
        sent_payload = sent.json()
        assert sent_payload["queued"] is True
        assert sent_payload["node"]["id"] == "agent1"
        assert sent_payload["node"]["last_message"] == "hello from phone"
        assert sent_payload["node"]["pending_count"] == 1
        assert sent_payload["conversation"]["messages"][-1]["role"] == "user"
        assert sent_payload["conversation"]["messages"][-1]["parts"][0]["text"] == "hello from phone"

        cfgs = client.get("/api/nodes/instances/configs?graph_id=default").json()["nodes"]
        cfg = next(item for item in cfgs if item["node_id"] == "agent1")
        assert cfg["pending_count"] == 1
        assert cfg["last_message"] == "hello from phone"
        assert ensure_calls == ["default"]
        assert wake_calls == ["default"]
    finally:
        if graph_runtime is not None and original_ensure is not None and original_wake is not None:
            graph_runtime._ensure_graph_runner = original_ensure
            graph_runtime._wake_graph_runner = original_wake
        backend._get_runtime_root = original_backend_runtime_root
        backend._get_resource_root = original_backend_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_resource_root
        node_runtime_module._get_runtime_root = original_node_runtime_runtime_root
        node_runtime_module._get_resource_root = original_node_runtime_resource_root
        mobile_api_module._get_runtime_root = original_mobile_runtime_root
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_mobile_api_rejects_unknown_pc():
    import src.web_backend as backend
    from fastapi.testclient import TestClient

    client = TestClient(backend.create_app())
    response = client.get("/api/mobile/pcs/missing/graphs")

    assert response.status_code == 404


def test_mobile_live_keeps_exact_config_node_id_when_config_node_id_case_differs(monkeypatch, tmp_path):
    import src.web_backend as backend
    import src.web_backend.mobile_api as mobile_api_module
    import src.web_backend.node_runtime as node_runtime_module
    import src.web_backend.runtime_paths as runtime_paths_module

    runtime_root = str(tmp_path / "AgentPark")
    resource_root = backend._get_runtime_root()
    os.makedirs(runtime_root, exist_ok=True)

    original_backend_runtime_root = backend._get_runtime_root
    original_backend_resource_root = backend._get_resource_root
    original_runtime_paths_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_resource_root = runtime_paths_module._get_resource_root
    original_node_runtime_runtime_root = node_runtime_module._get_runtime_root
    original_node_runtime_resource_root = node_runtime_module._get_resource_root
    original_mobile_runtime_root = mobile_api_module._get_runtime_root

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    node_runtime_module._get_runtime_root = lambda: runtime_root
    node_runtime_module._get_resource_root = lambda: resource_root
    mobile_api_module._get_runtime_root = lambda: runtime_root

    try:
        facade = backend.WebBackendFacade()
        app = facade.build()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {"id": "default", "name": "Default", "output_routes": {}}
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": "agent1", "type_id": "agent_node", "name": "agent1", "graph_id": "default"},
        )
        assert created.status_code == 200

        config_path = facade.core.graph_runtime._node_config_path("agent1", "default")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["node_id"] = "Agent1"
        cfg["name"] = "Agent1"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

        facade.core.node_live_outputs.update("default", "Agent1", "partial stream")
        facade.core.node_live_outputs.update_thinking("default", "Agent1", "checking sources")
        facade.core.node_live_outputs.update_activity(
            "default",
            "Agent1",
            {
                "id": "server_tool:ws_1",
                "type": "web_search",
                "label": "WebSearch",
                "status": "in_progress",
                "text": "AgentPark",
            },
        )

        nodes = client.get("/api/mobile/pcs/local/graphs/default/nodes")
        assert nodes.status_code == 200
        mobile_node = nodes.json()["nodes"][0]
        assert mobile_node["id"] == "agent1"
        assert mobile_node["name"] == "Agent1"

        live = client.get("/api/nodes/instances/Agent1/live?graph_id=default")
        assert live.status_code == 200
        assert live.json()["node_id"] == "Agent1"
        assert live.json()["live_message"] == "partial stream"
        assert live.json()["thinking_message"] == "checking sources"
        assert live.json()["activity_blocks"][0]["type"] == "web_search"

        conversation = client.get("/api/mobile/pcs/local/graphs/default/nodes/Agent1/conversation")
        assert conversation.status_code == 200
        assert conversation.json()["live_message"] == "partial stream"
        assert conversation.json()["thinking_message"] == "checking sources"
        assert conversation.json()["activity_blocks"][0]["label"] == "WebSearch"
    finally:
        backend._get_runtime_root = original_backend_runtime_root
        backend._get_resource_root = original_backend_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_resource_root
        node_runtime_module._get_runtime_root = original_node_runtime_runtime_root
        node_runtime_module._get_resource_root = original_node_runtime_resource_root
        mobile_api_module._get_runtime_root = original_mobile_runtime_root
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_mobile_conversation_returns_full_node_history(monkeypatch, tmp_path):
    import src.web_backend as backend
    import src.web_backend.mobile_api as mobile_api_module
    import src.web_backend.node_runtime as node_runtime_module
    import src.web_backend.runtime_paths as runtime_paths_module
    from src.message_protocol import build_text_envelope
    from src.web_backend.node_memory_store import append_node_memory_entry

    runtime_root = str(tmp_path / "AgentPark")
    resource_root = backend._get_runtime_root()
    os.makedirs(runtime_root, exist_ok=True)

    original_backend_runtime_root = backend._get_runtime_root
    original_backend_resource_root = backend._get_resource_root
    original_runtime_paths_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_resource_root = runtime_paths_module._get_resource_root
    original_node_runtime_runtime_root = node_runtime_module._get_runtime_root
    original_node_runtime_resource_root = node_runtime_module._get_resource_root
    original_mobile_runtime_root = mobile_api_module._get_runtime_root

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    node_runtime_module._get_runtime_root = lambda: runtime_root
    node_runtime_module._get_resource_root = lambda: resource_root
    mobile_api_module._get_runtime_root = lambda: runtime_root

    try:
        facade = backend.WebBackendFacade()
        app = facade.build()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {"id": "default", "name": "Default", "output_routes": {}}
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        assert client.post(
            "/api/nodes/instances",
            json={"node_id": "agent1", "type_id": "agent_node", "name": "Agent 1", "graph_id": "default"},
        ).status_code == 200

        memory_path = facade.core.graph_runtime._node_memory_path("agent1", "default")
        messages_path = facade.core.graph_runtime._node_messages_path("agent1", "default")
        for index in range(410):
            append_node_memory_entry(
                memory_path,
                messages_path,
                "user",
                build_text_envelope(f"message-{index:03d} " + ("x" * 70), role="user"),
            )

            conversation = client.get(
                "/api/mobile/pcs/local/graphs/default/nodes/agent1/conversation?history_mode=all"
            )
        assert conversation.status_code == 200
        payload = conversation.json()
        assert len(payload["text"]) > 20000
        assert len(payload["messages"]) == 410
        assert payload["messages"][0]["parts"][0]["text"].startswith("message-000")
        assert payload["messages"][-1]["parts"][0]["text"].startswith("message-409")
    finally:
        backend._get_runtime_root = original_backend_runtime_root
        backend._get_resource_root = original_backend_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_resource_root
        node_runtime_module._get_runtime_root = original_node_runtime_runtime_root
        node_runtime_module._get_resource_root = original_node_runtime_resource_root
        mobile_api_module._get_runtime_root = original_mobile_runtime_root
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_mobile_api_exposes_companion_as_readonly_graph_node(monkeypatch, tmp_path):
    import src.web_backend as backend
    import src.web_backend.mobile_api as mobile_api_module
    import src.web_backend.node_runtime as node_runtime_module
    import src.web_backend.runtime_paths as runtime_paths_module

    runtime_root = str(tmp_path / "AgentPark")
    resource_root = backend._get_runtime_root()
    graphs_dir = str(tmp_path / "memories")
    companion_graph_dir = os.path.join(graphs_dir, "Companion")
    companion_dir = os.path.join(companion_graph_dir, "Companion")
    os.makedirs(companion_dir, exist_ok=True)
    with open(os.path.join(companion_graph_dir, "config.json"), "w", encoding="utf-8") as f:
        f.write('{"id":"Companion","name":"Companion","output_routes":{}}')
    with open(os.path.join(companion_dir, "config.json"), "w", encoding="utf-8") as f:
        f.write(
            '{"graph_id":"Companion","node_id":"Companion","type_id":"agent_node","name":"Companion"}'
        )

    original_backend_runtime_root = backend._get_runtime_root
    original_backend_resource_root = backend._get_resource_root
    original_runtime_paths_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_resource_root = runtime_paths_module._get_resource_root
    original_runtime_paths_graphs_dir = runtime_paths_module._get_graphs_dir
    original_node_runtime_runtime_root = node_runtime_module._get_runtime_root
    original_node_runtime_resource_root = node_runtime_module._get_resource_root
    original_mobile_runtime_root = mobile_api_module._get_runtime_root

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    runtime_paths_module._get_graphs_dir = lambda: graphs_dir
    node_runtime_module._get_runtime_root = lambda: runtime_root
    node_runtime_module._get_resource_root = lambda: resource_root
    mobile_api_module._get_runtime_root = lambda: runtime_root

    try:
        facade = backend.WebBackendFacade()
        app = facade.build()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graphs = client.get("/api/mobile/pcs/local/graphs")
        assert graphs.status_code == 200
        graph_items = graphs.json()["instances"][0]["graphs"]
        companion_graph = next(item for item in graph_items if item["id"] == "Companion")
        assert companion_graph["readonly"] is True
        assert companion_graph["deletable"] is False
        assert companion_graph["editable"] is True
        assert companion_graph["display_name"] == "AgentPark.Companion"

        nodes = client.get("/api/mobile/pcs/local/graphs/Companion/nodes")
        assert nodes.status_code == 200
        companion_node = nodes.json()["nodes"][0]
        assert companion_node["id"] == "Companion"

        conversation = client.get("/api/mobile/pcs/local/graphs/Companion/nodes/Companion/conversation")
        assert conversation.status_code == 200
        assert conversation.json()["messages"] == []
    finally:
        backend._get_runtime_root = original_backend_runtime_root
        backend._get_resource_root = original_backend_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_resource_root
        runtime_paths_module._get_graphs_dir = original_runtime_paths_graphs_dir
        node_runtime_module._get_runtime_root = original_node_runtime_runtime_root
        node_runtime_module._get_resource_root = original_node_runtime_resource_root
        mobile_api_module._get_runtime_root = original_mobile_runtime_root
        shutil.rmtree(runtime_root, ignore_errors=True)
