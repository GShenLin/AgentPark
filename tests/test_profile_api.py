import json
import os
import shutil
import uuid


def _patch_profile_root(monkeypatch, tmp_path):
    from src.web_backend import profile_storage
    from src.web_backend import runtime_paths

    monkeypatch.setattr(profile_storage, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "get_workspace_root", lambda: str(tmp_path))


def _event_config(graph_id, node_id):
    from src.runtime_events.event_config_store import default_event_config

    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            graph_id: {
                node_id: [
                    {
                        "enabled": True,
                        "action": "context.produce",
                        "target": "builtin.environment_context",
                        "params": {"ttl": "current_run", "priority": "normal"},
                    }
                ]
            }
        }
    }
    return config


def test_agent_profile_from_node_upserts_and_strips_runtime_fields(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient
    from src.web_backend.node_config_service import node_config_service
    from src.web_backend.runtime_paths import _get_graphs_dir
    from src.web_backend.facade import WebBackendFacade

    graph_id = f"ut_profile_agent_{uuid.uuid4().hex[:8]}"
    node_id = "agent_profile_node"
    profile_id = "agent-default"
    graph_dir = os.path.join(_get_graphs_dir(), graph_id)

    try:
        facade = WebBackendFacade()
        client = TestClient(facade.build())
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200
        assert client.post("/api/events/apply", json={"config": _event_config(graph_id, node_id)}).json()["ok"] is True

        config_path = os.path.join(graph_dir, node_id, "config.json")
        cfg = node_config_service.read_strict(config_path)
        cfg.update(
            {
                "prefix": "hello",
                "state": "working",
                "pending": [{"payload": "queued"}],
                "last_message": "runtime preview",
                "runtime_events": [{"type": "runtime_notice"}],
            }
        )
        node_config_service.write(config_path, cfg)

        first = client.post(
            "/api/profiles/agents/from-node",
            json={
                "graph_id": graph_id,
                "node_id": node_id,
                "profile_id": profile_id,
                "profile_name": "Agent Default",
            },
        )
        assert first.status_code == 200
        second = client.post(
            "/api/profiles/agents/from-node",
            json={
                "graph_id": graph_id,
                "node_id": node_id,
                "profile_id": profile_id,
                "profile_name": "Agent Default Updated",
            },
        )
        assert second.status_code == 200

        profile_path = tmp_path / "agent" / f"{profile_id}.json"
        saved = json.loads(profile_path.read_text(encoding="utf-8"))
        assert saved["name"] == "Agent Default Updated"
        assert saved["node_type_id"] == "append_node"
        assert saved["fields"]["prefix"] == "hello"
        assert "state" not in saved["fields"]
        assert "pending" not in saved["fields"]
        assert "last_message" not in saved["fields"]
        assert "runtime_events" not in saved["fields"]
        assert saved["event_rules"]["OnInput"][0]["action"] == "context.produce"

        created_from_profile = client.post(
            f"/api/profiles/agents/{profile_id}/create",
            json={"graph_id": graph_id, "node_id": "agent_profile_copy", "name": "Agent Profile Copy"},
        )
        assert created_from_profile.status_code == 200
        event_config = json.loads((tmp_path / "config" / "events.json").read_text(encoding="utf-8"))
        copied_handlers = event_config["rules"]["OnInput"][graph_id]["agent_profile_copy"]
        assert copied_handlers == saved["event_rules"]["OnInput"]
        runtime_events = facade.core.runtime_events
        active_rules = runtime_events.registry.active().rule_index
        assert (graph_id, "agent_profile_copy", "OnInput") in active_rules
        emitted = runtime_events.emit(
            event="OnInput",
            graph_id=graph_id,
            node_id="agent_profile_copy",
            node_type_id="append_node",
            trace_id="agent-profile-event-trigger",
            payload={"input": "verify agent profile event"},
        )
        assert emitted["matched"] == 1
        assert emitted["executed"] == 1
        assert emitted["errors"] == []
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_agent_profile_editor_updates_three_explicit_sections(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient
    from src.web_backend.facade import WebBackendFacade

    profile_dir = tmp_path / "agent"
    profile_dir.mkdir(parents=True)
    profile_path = profile_dir / "editable-profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "id": "editable-profile",
                "name": "Editable Profile",
                "node_type_id": "agent_node",
                "source_graph_id": "default",
                "source_node_id": "GPT",
                "node_name": "GPT",
                "fields": {
                    "provider_id": "old-provider",
                    "instruction": "old instruction",
                    "system_prompt": "old system prompt",
                },
                "event_rules": {},
                "created_at": "2026-01-01T00:00:00+08:00",
                "updated_at": "2026-01-01T00:00:00+08:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    client = TestClient(WebBackendFacade().build())
    response = client.put(
        "/api/profiles/agents/editable-profile",
        json={
            "node_profiler": {
                "name": "Edited Profile",
                "node_type_id": "agent_node",
                "source_graph_id": "new-graph",
                "source_node_id": "NewNode",
                "node_name": "New Node",
                "fields": {
                    "provider_id": "new-provider",
                    "tools": ["system_tools"],
                },
                "event_rules": {"OnInput": []},
            },
            "instruction": "new instruction",
            "system_prompt": "new system prompt",
        },
    )

    assert response.status_code == 200
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    assert saved["id"] == "editable-profile"
    assert saved["name"] == "Edited Profile"
    assert saved["source_graph_id"] == "new-graph"
    assert saved["fields"] == {
        "provider_id": "new-provider",
        "tools": ["system_tools"],
        "instruction": "new instruction",
        "system_prompt": "new system prompt",
    }
    assert saved["event_rules"] == {"OnInput": []}
    assert saved["created_at"] == "2026-01-01T00:00:00+08:00"


def test_agent_profile_editor_rejects_prompt_fields_inside_node_profiler(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient
    from src.web_backend.facade import WebBackendFacade

    profile_dir = tmp_path / "agent"
    profile_dir.mkdir(parents=True)
    (profile_dir / "strict-profile.json").write_text(
        json.dumps(
            {
                "id": "strict-profile",
                "name": "Strict Profile",
                "node_type_id": "agent_node",
                "fields": {},
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(WebBackendFacade().build())
    response = client.put(
        "/api/profiles/agents/strict-profile",
        json={
            "node_profiler": {
                "name": "Strict Profile",
                "node_type_id": "agent_node",
                "fields": {"instruction": "wrong section"},
                "event_rules": {},
            },
            "instruction": "dedicated instruction",
            "system_prompt": "",
        },
    )

    assert response.status_code == 400
    assert "dedicated editor fields" in response.json()["detail"]


def test_load_agent_profile_updates_fields_and_events_without_renaming_node(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient
    from src.runtime_events.event_config_store import default_event_config
    from src.web_backend.facade import WebBackendFacade
    from src.web_backend.node_config_service import node_config_service
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_profile_load_{uuid.uuid4().hex[:8]}"
    source_node_id = "profile_source"
    target_node_id = "profile_target"
    profile_id = "load-agent-target"
    graph_dir = os.path.join(_get_graphs_dir(), graph_id)

    try:
        facade = WebBackendFacade()
        client = TestClient(facade.build())
        assert client.post(
            "/api/nodes/instances",
            json={
                "node_id": source_node_id,
                "type_id": "append_node",
                "name": "Profile Source Name",
                "graph_id": graph_id,
            },
        ).status_code == 200
        assert client.post(
            "/api/nodes/instances",
            json={
                "node_id": target_node_id,
                "type_id": "append_node",
                "name": "Keep This Node Name",
                "graph_id": graph_id,
            },
        ).status_code == 200

        source_config_path = os.path.join(graph_dir, source_node_id, "config.json")
        target_config_path = os.path.join(graph_dir, target_node_id, "config.json")
        source_config = node_config_service.read_strict(source_config_path)
        source_config["name"] = "Profile Source Name"
        source_config["prefix"] = "loaded profile prefix"
        node_config_service.write(source_config_path, source_config)
        target_config = node_config_service.read_strict(target_config_path)
        target_config["name"] = "Keep This Node Name"
        target_config["prefix"] = "old target prefix"
        node_config_service.write(target_config_path, target_config)

        assert client.post(
            "/api/events/apply",
            json={"config": _event_config(graph_id, source_node_id)},
        ).json()["ok"] is True
        assert client.post(
            "/api/profiles/agents/from-node",
            json={
                "graph_id": graph_id,
                "node_id": source_node_id,
                "profile_id": profile_id,
                "profile_name": "Load Agent Target",
            },
        ).status_code == 200

        target_event_config = default_event_config()
        target_event_config["rules"] = {
            "ToolFailure": {
                graph_id: {
                    target_node_id: [
                        {
                            "enabled": True,
                            "action": "notice.write",
                            "target": "builtin.runtime_event_notice",
                            "params": {},
                        }
                    ]
                }
            }
        }
        assert client.post("/api/events/apply", json={"config": target_event_config}).json()["ok"] is True

        loaded = client.post(
            f"/api/profiles/agents/{profile_id}/load",
            json={"graph_id": graph_id, "node_id": target_node_id},
        )
        assert loaded.status_code == 200
        payload = loaded.json()
        assert payload["config"]["after"]["name"] == "Keep This Node Name"
        assert payload["config"]["after"]["prefix"] == "loaded profile prefix"

        persisted_target = node_config_service.read_strict(target_config_path)
        assert persisted_target["name"] == "Keep This Node Name"
        assert persisted_target["prefix"] == "loaded profile prefix"
        assert facade.core.runtime_events.export_source_event_rules(graph_id, target_node_id) == {
            "OnInput": _event_config(graph_id, source_node_id)["rules"]["OnInput"][graph_id][source_node_id]
        }
        active_rules = facade.core.runtime_events.registry.active().rule_index
        assert (graph_id, target_node_id, "OnInput") in active_rules
        assert (graph_id, target_node_id, "ToolFailure") not in active_rules
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_agent_profile_delete_removes_profile_file(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_profile_agent_delete_{uuid.uuid4().hex[:8]}"
    node_id = "agent_profile_delete_node"
    profile_id = "delete-agent-target"
    graph_dir = os.path.join(_get_graphs_dir(), graph_id)

    try:
        client = TestClient(backend.create_app())
        assert client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id},
        ).status_code == 200
        assert client.post(
            "/api/profiles/agents/from-node",
            json={
                "graph_id": graph_id,
                "node_id": node_id,
                "profile_id": profile_id,
                "profile_name": "Delete Agent Target",
            },
        ).status_code == 200

        profile_path = tmp_path / "agent" / f"{profile_id}.json"
        assert profile_path.exists()

        deleted = client.delete(f"/api/profiles/agents/{profile_id}")

        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True, "profile_id": profile_id, "deleted": True}
        assert not profile_path.exists()
        listed = client.get("/api/profiles/agents")
        assert listed.status_code == 200
        assert all(item["id"] != profile_id for item in listed.json().get("profiles", []))

        deleted_again = client.delete(f"/api/profiles/agents/{profile_id}")
        assert deleted_again.status_code == 404
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_graph_profile_create_retargets_graph_and_node_config_ids(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient
    from src.web_backend.node_config_service import node_config_service
    from src.web_backend.runtime_paths import _get_graphs_dir
    from src.web_backend.facade import WebBackendFacade

    source_graph_id = f"ut_profile_src_{uuid.uuid4().hex[:8]}"
    target_graph_id = f"ut_profile_dst_{uuid.uuid4().hex[:8]}"
    node_id = "profile_graph_node"
    profile_id = "research-flow"
    graphs_dir = _get_graphs_dir()
    source_dir = os.path.join(graphs_dir, source_graph_id)
    target_dir = os.path.join(graphs_dir, target_graph_id)

    try:
        facade = WebBackendFacade()
        client = TestClient(facade.build())
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": source_graph_id, "ui": {"x": 11, "y": 22}},
        )
        assert created.status_code == 200
        assert client.post(
            "/api/events/apply",
            json={"config": _event_config(source_graph_id, node_id)},
        ).json()["ok"] is True
        saved_graph = client.post(
            f"/api/graphs/{source_graph_id}",
            json={
                "graph": {
                    "id": source_graph_id,
                    "name": source_graph_id,
                    "nodes": [],
                    "output_routes": {
                        node_id: [{"output_index": 0, "targets": [{"node_id": node_id, "input_index": 0}]}],
                    },
                }
            },
        )
        assert saved_graph.status_code == 200

        config_path = os.path.join(source_dir, node_id, "config.json")
        cfg = node_config_service.read_strict(config_path)
        cfg.update(
            {
                "suffix": "world",
                "state": "working",
                "pending": [{"payload": "queued"}],
                "last_message": "runtime preview",
                "runtime_tool_calls": [{"name": "tool"}],
            }
        )
        node_config_service.write(config_path, cfg)

        saved_profile = client.post(
            "/api/profiles/graphs/from-graph",
            json={"graph_id": source_graph_id, "profile_id": profile_id, "profile_name": "Research Flow"},
        )
        assert saved_profile.status_code == 200

        created_graph = client.post(f"/api/profiles/graphs/{profile_id}/create", json={"graph_id": target_graph_id})
        assert created_graph.status_code == 200

        graph_config = json.loads(open(os.path.join(target_dir, "config.json"), "r", encoding="utf-8").read())
        assert graph_config["id"] == target_graph_id
        assert graph_config["name"] == target_graph_id

        node_config_path = os.path.join(target_dir, node_id, "config.json")
        target_cfg = json.loads(open(node_config_path, "r", encoding="utf-8").read())
        assert target_cfg["node_id"] == node_id
        assert target_cfg["graph_id"] == target_graph_id
        assert target_cfg["type_id"] == "append_node"
        assert target_cfg["suffix"] == "world"
        for runtime_key in ("state", "pending", "last_message", "runtime_tool_calls"):
            assert runtime_key not in target_cfg
        assert not os.path.exists(os.path.join(target_dir, node_id, "runtime_state.json"))
        assert not os.path.exists(os.path.join(target_dir, node_id, "memory.md"))
        assert not os.path.exists(os.path.join(target_dir, node_id, "messages.jsonl"))

        profile = json.loads((tmp_path / "graph" / f"{profile_id}.json").read_text(encoding="utf-8"))
        assert profile["graph"]["id"] == source_graph_id
        assert profile["node_configs"][0]["graph_id"] == source_graph_id
        assert profile["node_configs"][0]["fields"]["suffix"] == "world"
        assert "pending" not in profile["node_configs"][0]["fields"]
        assert profile["node_configs"][0]["event_rules"]["OnInput"][0]["action"] == "context.produce"
        event_config = json.loads((tmp_path / "config" / "events.json").read_text(encoding="utf-8"))
        target_handlers = event_config["rules"]["OnInput"][target_graph_id][node_id]
        assert target_handlers == profile["node_configs"][0]["event_rules"]["OnInput"]
        runtime_events = facade.core.runtime_events
        active_rules = runtime_events.registry.active().rule_index
        assert (target_graph_id, node_id, "OnInput") in active_rules
        emitted = runtime_events.emit(
            event="OnInput",
            graph_id=target_graph_id,
            node_id=node_id,
            node_type_id="append_node",
            trace_id="graph-profile-event-trigger",
            payload={"input": "verify graph profile event"},
        )
        assert emitted["matched"] == 1
        assert emitted["executed"] == 1
        assert emitted["errors"] == []
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)
        shutil.rmtree(target_dir, ignore_errors=True)


def test_graph_profile_create_rejects_existing_graph_id(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    source_graph_id = f"ut_profile_exists_src_{uuid.uuid4().hex[:8]}"
    target_graph_id = f"ut_profile_exists_dst_{uuid.uuid4().hex[:8]}"
    profile_id = "existing-target"
    graphs_dir = _get_graphs_dir()
    source_dir = os.path.join(graphs_dir, source_graph_id)
    target_dir = os.path.join(graphs_dir, target_graph_id)

    try:
        client = TestClient(backend.create_app())
        assert client.post("/api/nodes/instances", json={"node_id": "n1", "type_id": "append_node", "graph_id": source_graph_id}).status_code == 200
        assert client.post("/api/nodes/instances", json={"node_id": "n2", "type_id": "append_node", "graph_id": target_graph_id}).status_code == 200
        assert client.post(
            "/api/profiles/graphs/from-graph",
            json={"graph_id": source_graph_id, "profile_id": profile_id, "profile_name": "Existing Target"},
        ).status_code == 200

        response = client.post(f"/api/profiles/graphs/{profile_id}/create", json={"graph_id": target_graph_id})

        assert response.status_code == 409
        assert "already exists" in response.json().get("detail", "")
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)
        shutil.rmtree(target_dir, ignore_errors=True)


def test_graph_profile_delete_removes_profile_file(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    source_graph_id = f"ut_profile_delete_src_{uuid.uuid4().hex[:8]}"
    profile_id = "delete-target"
    source_dir = os.path.join(_get_graphs_dir(), source_graph_id)

    try:
        client = TestClient(backend.create_app())
        assert client.post(
            "/api/nodes/instances",
            json={"node_id": "n1", "type_id": "append_node", "graph_id": source_graph_id},
        ).status_code == 200
        assert client.post(
            "/api/profiles/graphs/from-graph",
            json={"graph_id": source_graph_id, "profile_id": profile_id, "profile_name": "Delete Target"},
        ).status_code == 200

        profile_path = tmp_path / "graph" / f"{profile_id}.json"
        assert profile_path.exists()

        deleted = client.delete(f"/api/profiles/graphs/{profile_id}")

        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True, "profile_id": profile_id, "deleted": True}
        assert not profile_path.exists()
        listed = client.get("/api/profiles/graphs")
        assert listed.status_code == 200
        assert all(item["id"] != profile_id for item in listed.json().get("profiles", []))

        deleted_again = client.delete(f"/api/profiles/graphs/{profile_id}")
        assert deleted_again.status_code == 404
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)
