import logging

import pytest


def _write_json(path, payload):
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict) and payload.get("node_id"):
        from src.web_backend.state_store import _write_json_dict

        _write_json_dict(str(path), payload)
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_companion_mcp_decodes_non_ascii_caller_headers():
    from src.mcp.caller_context_headers import encode_caller_header_value
    from src.web_backend.companion_mcp import _caller_from_context

    class Headers:
        def get(self, name):
            values = {
                "x-agentpark-graph-id": encode_caller_header_value("默认图"),
                "x-agentpark-node-id": encode_caller_header_value("核对答案"),
            }
            return values.get(name)

    class Request:
        headers = Headers()

    class RequestContext:
        request = Request()

    class Context:
        request_context = RequestContext()

    assert _caller_from_context(Context()) == {"graph_id": "默认图", "node_id": "核对答案"}


def test_companion_mcp_tools_operate_on_backend_domains(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    _write_json(
        graph_dir / "n1" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "n1",
            "graph_id": "default",
            "type_id": "echo_node",
            "name": "Echo",
            "state": "working",
            "last_message": "busy",
            "inflight": {"trace_id": "fixture-working"},
            "working_path": str(tmp_path),
            "tools": ["file_read_tools", "rg_tools"],
            "mcp_servers": ["agentpark-companion"],
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    core = backend.WebBackendFacade().core
    tools = CompanionMcpTools(core)

    assert tools.list_graph()["graphs"][0]["id"] == "default"
    nodes = tools.list_node(graph_id="default")["nodes"]
    assert [item["node_id"] for item in nodes] == ["n1"]
    assert nodes[0]["capabilities"]["tools"] == ["file_read_tools", "rg_tools"]
    assert nodes[0]["capabilities"]["mcp_servers"] == ["agentpark-companion"]
    assert nodes[0]["capabilities"]["can"]["read_local_files"] is True
    assert nodes[0]["capabilities"]["can"]["search_local_files"] is True
    assert tools.get_node_last_message(graph_id="default", node_id="n1")["last_message"] == "busy"
    statuses = tools.list_node_status(graph_id="default")["nodes"]
    assert statuses[0]["node_id"] == "n1"
    assert statuses[0]["working_path"] == str(tmp_path)
    assert statuses[0]["can"]["read_local_files"] is True
    assert statuses[0]["capabilities"]["tools"] == ["file_read_tools", "rg_tools"]
    assert tools.get_working_node(graph_id="default")["nodes"][0]["node_id"] == "n1"

    changed = tools.change_node_config(graph_id="default", node_id="n1", fields={"mode": "chat"})

    assert changed["ok"] is True
    assert changed["after"]["mode"] == "chat"
    assert "mode" in changed["changed_fields"]


def test_companion_mcp_link_tools_manage_graph_links(monkeypatch, tmp_path):
    import json

    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp_links import CompanionMcpLinkTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(
        graph_dir / "config.json",
        {
            "id": "default",
            "name": "Default Graph",
            "output_routes": {
                "source": [{"output_index": 0, "targets": [{"node_id": "target", "input_index": 0}]}],
            },
        },
    )
    _write_json(
        graph_dir / "source" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "source",
            "graph_id": "default",
            "type_id": "echo_node",
            "input_num": 1,
            "output_num": 2,
        },
    )
    _write_json(
        graph_dir / "target" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "target",
            "graph_id": "default",
            "type_id": "echo_node",
            "input_num": 1,
            "output_num": 1,
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    core = backend.WebBackendFacade().core
    tools = CompanionMcpLinkTools(core)

    listed = tools.list_link(graph_id="default")
    assert listed["ok"] is True
    assert listed["count"] == 1
    existing_link_id = listed["links"][0]["id"]
    assert existing_link_id == "route-source-0-target-0"

    created = tools.connect_node(
        graph_id="default",
        from_node="source",
        to_node="target",
        from_output_index=1,
        to_input_index=0,
    )

    assert created["ok"] is True
    assert created["created"] is True
    assert created["link"]["from"] == {"node": "source", "index": 1}
    assert created["count"] == 2
    graph_event = core.graph_events.get("default")
    assert graph_event["event"] == "graph_save_api"
    assert graph_event["save_reason"] == "companion_connect_node"

    duplicate = tools.connect_node(
        graph_id="default",
        from_node="source",
        to_node="target",
        from_output_index=1,
        to_input_index=0,
    )

    assert duplicate["ok"] is True
    assert duplicate["created"] is False
    assert duplicate["count"] == 2

    removed_by_endpoint = tools.disconnect_node(
        graph_id="default",
        from_node="source",
        to_node="target",
        from_output_index=1,
        to_input_index=0,
    )

    assert removed_by_endpoint["ok"] is True
    assert removed_by_endpoint["removed_count"] == 1

    removed_by_id = tools.disconnect_node(graph_id="default", link_id=existing_link_id)

    assert removed_by_id["ok"] is True
    assert removed_by_id["removed"][0]["id"] == existing_link_id
    saved = json.loads((graph_dir / "config.json").read_text(encoding="utf-8"))
    assert "links" not in saved
    assert saved["output_routes"] == {}


def test_companion_mcp_connect_node_validates_ports(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp_links import CompanionMcpLinkTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    _write_json(
        graph_dir / "source" / "config.json",
        {"schemaVersion": 1, "node_id": "source", "graph_id": "default", "type_id": "echo_node", "output_num": 1},
    )
    _write_json(
        graph_dir / "target" / "config.json",
        {"schemaVersion": 1, "node_id": "target", "graph_id": "default", "type_id": "echo_node", "input_num": 1},
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    result = CompanionMcpLinkTools(backend.WebBackendFacade().core).connect_node(
        graph_id="default",
        from_node="source",
        to_node="target",
        from_output_index=1,
        to_input_index=0,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_port"


def test_companion_mcp_aggregate_tools_propagate_structured_errors(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    _write_json(graphs_dir / "default" / "config.json", {"id": "default", "name": "Default Graph"})
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    core = backend.WebBackendFacade().core

    def broken_list_node_instance_configs(*, graph_id="default"):
        raise ValueError(f"broken graph {graph_id}")

    object.__setattr__(core.node_ops, "list_node_instance_configs", broken_list_node_instance_configs)
    tools = CompanionMcpTools(core)

    status_result = tools.list_node_status(graph_id="default")
    working_result = tools.get_working_node(graph_id="default")

    assert status_result["ok"] is False
    assert status_result["error"]["code"] == "invalid_request"
    assert working_result["ok"] is False
    assert working_result["error"]["code"] == "invalid_request"


def test_companion_mcp_marks_self_and_blocks_unintentional_self_send(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    _write_json(
        graph_dir / "self-node" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "self-node",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Self",
            "state": "idle",
            "last_message": "ready",
        },
    )
    _write_json(
        graph_dir / "worker" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "worker",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Worker",
            "state": "idle",
            "last_message": "ready",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    tools = CompanionMcpTools(backend.WebBackendFacade().core)
    caller = {"graph_id": "default", "node_id": "self-node"}

    meta = tools.get_companion_meta(caller=caller)
    assert meta["self"]["node_id"] == "self-node"
    assert meta["self"]["is_self"] is True
    statuses = tools.list_node_status(graph_id="default", caller=caller)["nodes"]
    by_id = {item["node_id"]: item for item in statuses}
    assert by_id["self-node"]["is_self"] is True
    assert by_id["worker"]["is_self"] is False

    blocked = tools.send_message_to_node(
        graph_id="default",
        node_id="self-node",
        message="loop",
        wait_until_idle=False,
        caller=caller,
    )

    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "self_recursion_blocked"


def test_companion_mcp_send_waits_for_node_result(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    config_path = graph_dir / "worker" / "config.json"
    _write_json(
        config_path,
        {
            "schemaVersion": 1,
            "node_id": "worker",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Worker",
            "state": "idle",
            "last_message": "ready",
            "pending_count": 0,
            "node_event_seq": 7,
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    core = backend.WebBackendFacade().core

    def fake_emit_graph(graph_id, payload):
        assert graph_id == "default"
        assert payload["from_id"] == "worker"
        _write_json(
            config_path,
            {
                "schemaVersion": 1,
                "node_id": "worker",
                "graph_id": "default",
                "type_id": "agent_node",
                "name": "Worker",
                "state": "idle",
                "last_message": "done",
                "pending_count": 0,
                "node_event_seq": 8,
                "last_run_at": "2026-06-26 16:00:00",
            },
        )
        return {"ok": True, "queued": True, "trace_id": "trace-1"}

    object.__setattr__(core.graph_api, "emit_graph", fake_emit_graph)

    result = CompanionMcpTools(core).send_message_to_node(
        graph_id="default",
        node_id="worker",
        message="work",
        wait_until_idle=True,
        timeout_seconds=1,
    )

    assert result["sent"]["trace_id"] == "trace-1"
    assert result["node"]["last_message"] == "done"
    assert result["node"]["message_id"] == "8"
    assert result["node"]["wait"]["node_event_seq"] == 8
    assert result["node"]["wait"]["elapsed_seconds"] >= 0
    assert result["node"]["wait"]["completed"] is True
    assert result["node"]["wait"]["timeout"] is False


def test_companion_mcp_send_wait_matches_request_id_when_node_keeps_working(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    config_path = graph_dir / "worker" / "config.json"
    _write_json(
        config_path,
        {
            "schemaVersion": 1,
            "node_id": "worker",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Worker",
            "state": "idle",
            "last_message": "ready",
            "pending_count": 0,
            "node_event_seq": 10,
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    core = backend.WebBackendFacade().core

    def fake_emit_graph(graph_id, payload):
        request_id = payload["trace_id"]
        _write_json(
            config_path,
            {
                "schemaVersion": 1,
                "node_id": "worker",
                "graph_id": "default",
                "type_id": "agent_node",
                "name": "Worker",
                "state": "working",
                "last_message": "next request already running",
                "pending_count": 0,
                "node_event_seq": 12,
                "completed_requests": [
                    {
                        "request_id": request_id,
                        "trace_id": request_id,
                        "role": "assistant",
                        "message": "matched result",
                        "state": "idle",
                        "node_event_seq": 11,
                    }
                ],
            },
        )
        return {"ok": True, "queued": True, "trace_id": request_id, "request_id": request_id}

    object.__setattr__(core.graph_api, "emit_graph", fake_emit_graph)

    result = CompanionMcpTools(core).send_message_to_node(
        graph_id="default",
        node_id="worker",
        message="work",
        wait_until_idle=True,
        timeout_seconds=1,
    )

    assert result["request_id"] == result["sent"]["request_id"]
    assert result["node"]["last_message"] == "matched result"
    assert result["node"]["state"] == "idle"
    assert result["node"]["current_state"] == "working"
    assert result["node"]["wait"]["request_id"] == result["request_id"]


def test_companion_mcp_real_worker_records_completed_request(monkeypatch, tmp_path):
    import os

    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    config_path = graph_dir / "echo1" / "config.json"
    _write_json(
        config_path,
        {
            "schemaVersion": 1,
            "node_id": "echo1",
            "graph_id": "default",
            "type_id": "echo_node",
            "name": "Echo",
            "state": "idle",
            "input_num": 1,
            "output_num": 1,
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_nodes_dir", lambda: os.path.abspath("nodes"))

    core = backend.WebBackendFacade().core
    result = CompanionMcpTools(core).send_message_to_node(
        graph_id="default",
        node_id="echo1",
        message="hello",
        wait_until_idle=True,
        timeout_seconds=5,
    )

    assert result["node"]["last_message"] == "hello"
    completed = result["node"]["matched_request"]
    assert completed["request_id"] == result["request_id"]
    assert completed["message"] == "hello"


def test_companion_mcp_returns_structured_timeout_next_action(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    _write_json(
        graph_dir / "worker" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "worker",
            "graph_id": "default",
            "type_id": "agent_node",
            "state": "working",
            "last_message": "running",
            "pending_count": 0,
            "inflight": {"payload": "work"},
            "node_event_seq": 4,
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    node = CompanionMcpTools(backend.WebBackendFacade().core).get_node_last_message(
        graph_id="default",
        node_id="worker",
        wait_until_idle=True,
        timeout_seconds=0,
        since_message_id="4",
    )

    assert node["wait"]["timeout"] is True
    assert "next_action" in node["wait"]


def test_companion_mcp_list_graph_adds_agent_facing_metadata(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "description": "Demo"})
    _write_json(
        graph_dir / "n1" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "n1",
            "graph_id": "default",
            "type_id": "echo_node",
            "state": "working",
            "inflight": {"payload": "work"},
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    payload = CompanionMcpTools(backend.WebBackendFacade().core).list_graph()

    graph = payload["graphs"][0]
    assert graph["graph_id"] == "default"
    assert graph["description"] == "Demo"
    assert graph["node_count"] == 1
    assert graph["state"] == "working"


def test_companion_meta_self_is_stable_identity_only(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph"})
    _write_json(
        graph_dir / "self" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "self",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Self",
            "provider": "demo-provider",
            "model": "demo-model",
            "state": "idle",
            "last_message": "large dynamic output",
            "working_path": str(tmp_path),
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    meta = CompanionMcpTools(backend.WebBackendFacade().core).get_companion_meta(
        caller={"graph_id": "default", "node_id": "self"}
    )

    assert meta["max_timeout_seconds"] == 600.0
    assert meta["self"]["provider"] == "demo-provider"
    assert meta["self"]["model"] == "demo-model"
    assert "last_message" not in meta["self"]
    assert "live_message" not in meta["self"]


def test_companion_mcp_rejects_non_editable_config_fields(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools
    from src.web_backend.companion_mcp_payloads import EDITABLE_NODE_CONFIG_FIELDS

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph"})
    _write_json(
        graph_dir / "n1" / "config.json",
        {"schemaVersion": 1, "node_id": "n1", "graph_id": "default", "type_id": "agent_node", "state": "idle"},
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    result = CompanionMcpTools(backend.WebBackendFacade().core).change_node_config(
        graph_id="default",
        node_id="n1",
        fields={"provider_id": "secret"},
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "field_not_editable"
    assert "collaboration_mode" in EDITABLE_NODE_CONFIG_FIELDS


def test_companion_mcp_wait_timeout_has_no_artificial_170_second_cap():
    import src.web_backend as backend
    from src.web_backend.companion_mcp import CompanionMcpTools

    assert CompanionMcpTools(backend.WebBackendFacade().core)._timeout_seconds(180) == 180.0


def test_companion_mcp_reports_truncated_last_message_hint(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    _write_json(
        graph_dir / "long" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "long",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Long",
            "state": "idle",
            "last_message": "x" * 10000,
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    node = CompanionMcpTools(backend.WebBackendFacade().core).get_node_last_message(
        graph_id="default",
        node_id="long",
    )

    assert node["last_message_truncated"] is True
    assert node["memory_hint"] == {"tool": "get_node_memory", "max_chars": 20000}


def test_companion_mcp_reports_last_error(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    _write_json(
        graph_dir / "bad" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "bad",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Bad",
            "state": "idle",
            "last_message": "Error: RuntimeError: boom",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    node = CompanionMcpTools(backend.WebBackendFacade().core).get_node_last_message(
        graph_id="default",
        node_id="bad",
    )

    assert node["last_error"] == {"source": "last_message", "message": "Error: RuntimeError: boom"}


def test_companion_mcp_get_node_memory_supports_pagination(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph"})
    _write_json(
        graph_dir / "n1" / "config.json",
        {"schemaVersion": 1, "node_id": "n1", "graph_id": "default", "type_id": "agent_node", "state": "idle"},
    )
    messages_path = graph_dir / "n1" / "messages.jsonl"
    messages_path.write_text(
        "\n".join(
            [
                '{"role":"user","parts":[{"type":"text","text":"first"}]}',
                '{"role":"assistant","parts":[{"type":"text","text":"second"}]}',
                '{"role":"user","parts":[{"type":"text","text":"third"}]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    payload = CompanionMcpTools(backend.WebBackendFacade().core).get_node_memory(
        graph_id="default",
        node_id="n1",
        start_seq=2,
        offset_chars=1,
        max_chars=8,
    )

    assert [message["parts"][0]["text"] for message in payload["messages"]] == ["second", "third"]
    assert payload["text"] == "econd\nth"
    assert payload["page"]["truncated"] is True


def test_companion_capabilities_web_search_requires_exact_name():
    from src.web_backend.companion_capabilities import infer_node_can

    broad = infer_node_can({"tools": ["file_search"], "mcp_servers": ["web_fetch"]})
    exact = infer_node_can({"tools": ["web_search"]})

    assert broad["web_search"] is False
    assert exact["web_search"] is True


def test_companion_mcp_stop_node_clears_pending(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import CompanionMcpTools

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    _write_json(
        graph_dir / "stuck" / "config.json",
        {
            "schemaVersion": 1,
            "node_id": "stuck",
            "graph_id": "default",
            "type_id": "agent_node",
            "name": "Stuck",
            "state": "idle",
            "pending": [{"payload": "queued"}],
            "pending_count": 1,
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    result = CompanionMcpTools(backend.WebBackendFacade().core).stop_node(
        graph_id="default",
        node_id="stuck",
        reason="unit test",
    )

    assert result["ok"] is True
    assert result["after"]["state"] == "idle"
    assert result["after"]["pending_count"] == 0
    assert result["after"]["last_message"] == "Stopped. Pending work cleared."


def test_node_event_seq_increments_on_last_message(tmp_path):
    from src.web_backend.state_store import _read_json_dict, _set_node_config_last_message

    config_path = tmp_path / "config.json"
    _write_json(config_path, {"schemaVersion": 1, "node_id": "n1", "node_event_seq": 2})

    _set_node_config_last_message(str(config_path), "hello")

    payload = _read_json_dict(str(config_path))
    assert payload["last_message"] == "hello"
    assert payload["node_event_seq"] == 3


def test_companion_mcp_endpoint_exposes_requested_tools(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.companion_mcp import build_companion_mcp

    graphs_dir = tmp_path / "memories"
    _write_json(graphs_dir / "default" / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    mcp = build_companion_mcp(backend.WebBackendFacade().core)
    names = sorted(tool.name for tool in mcp._tool_manager.list_tools())

    assert names == [
        "change_node_config",
        "connect_node",
        "disconnect_node",
        "get_companion_meta",
        "get_node_last_message",
        "get_node_memory",
        "get_working_node",
        "list_graph",
        "list_link",
        "list_node",
        "list_node_status",
        "send_message_to_node",
        "stop_node",
    ]


def test_companion_mcp_filters_terminating_none_session_noise():
    from src.web_backend.companion_mcp import _TerminatingNoneSessionFilter

    session_filter = _TerminatingNoneSessionFilter()
    noisy = logging.LogRecord("mcp", logging.INFO, __file__, 1, "Terminating session: None", (), None)
    useful = logging.LogRecord("mcp", logging.INFO, __file__, 1, "Terminating session: abc", (), None)

    assert session_filter.filter(noisy) is False
    assert session_filter.filter(useful) is True


def test_graph_event_store_receives_logged_runtime_events(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    _write_json(graphs_dir / "default" / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    facade = backend.WebBackendFacade()
    facade.build()
    facade.core.graph_runtime._log_graph_event("default", "emit_enqueued", node_id="n1")

    payload = facade.core.graph_events.get("default")

    assert payload["event"] == "emit_enqueued"
    assert payload["graph_id"] == "default"
    assert payload["node_id"] == "n1"
    assert int(payload["version"]) >= 1


def test_runtime_log_appends_without_stream_publish(monkeypatch, tmp_path):
    import json

    import src.web_backend as backend
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    _write_json(graphs_dir / "default" / "config.json", {"id": "default", "name": "Default Graph", "output_routes": {}})
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    facade = backend.WebBackendFacade()
    facade.build()
    facade.core.graph_runtime._append_runtime_log(
        "default",
        "runtime_notice",
        trace_id="trace-1",
        node_instance_id="n1",
        node_type_id="agent_node",
        message="running",
    )

    events_path = graphs_dir / "default" / "runtime.events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert events[-1]["event"] == "runtime_notice"
    assert events[-1]["graph_id"] == "default"
    assert events[-1]["node_instance_id"] == "n1"
    assert events[-1]["message"] == "running"
    assert facade.core.graph_events.get("default") == {"graph_id": "default", "version": 0}
