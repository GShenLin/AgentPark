import json
import os
import uuid


def _client(monkeypatch, tmp_path):
    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src import workspace_settings
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({"undo": {"maxSteps": 5}}),
        encoding="utf-8",
    )
    return TestClient(backend.create_app())


def test_delete_node_can_be_undone(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    graph_id = f"undo_node_{uuid.uuid4().hex[:8]}"
    node_id = "restorable"
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": node_id, "type_id": "missing_node", "graph_id": graph_id},
    )
    assert created.status_code == 200
    node_dir = tmp_path / "memories" / graph_id / node_id

    deleted = client.delete(f"/api/nodes/instances/{node_id}?graph_id={graph_id}")

    assert deleted.status_code == 200
    token = deleted.json().get("undo_token")
    assert token
    assert not node_dir.exists()

    restored = client.post(f"/api/undo/{token}")

    assert restored.status_code == 200
    assert restored.json()["kind"] == "delete_node"
    assert node_dir.is_dir()
    assert client.post(f"/api/undo/{token}").status_code == 404


def test_delete_node_removes_event_rules_and_undo_restores_them(monkeypatch, tmp_path):
    from src.runtime_events.event_config_store import default_event_config

    client = _client(monkeypatch, tmp_path)
    graph_id = f"undo_node_events_{uuid.uuid4().hex[:8]}"
    node_id = "restorable"
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": node_id, "type_id": "missing_node", "graph_id": graph_id},
    )
    assert created.status_code == 200
    events_path = tmp_path / "config" / "events.json"
    events = default_event_config()
    events["rules"] = {
        "OnInput": {
            graph_id: {
                node_id: [
                    {
                        "enabled": True,
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["context.md"], "role": "developer"},
                    }
                ]
            }
        }
    }
    events_path.write_text(json.dumps(events), encoding="utf-8")

    deleted = client.delete(f"/api/nodes/instances/{node_id}?graph_id={graph_id}")

    assert deleted.status_code == 200
    assert deleted.json()["removed_event_handlers"] == 1
    assert json.loads(events_path.read_text(encoding="utf-8"))["rules"] == {}

    restored = client.post(f"/api/undo/{deleted.json()['undo_token']}")

    assert restored.status_code == 200
    restored_rules = json.loads(events_path.read_text(encoding="utf-8"))["rules"]
    assert restored_rules["OnInput"][graph_id][node_id][0]["action"] == "context.append_file"


def test_delete_graph_can_be_undone(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    graph_id = f"undo_graph_{uuid.uuid4().hex[:8]}"
    saved = client.post(
        f"/api/graphs/{graph_id}",
        json={"graph": {"id": graph_id, "name": "Undo Graph", "output_routes": {}}},
    )
    assert saved.status_code == 200
    graph_dir = tmp_path / "memories" / graph_id

    deleted = client.delete(f"/api/graphs/{graph_id}")

    assert deleted.status_code == 200
    token = deleted.json().get("undo_token")
    assert token
    assert not graph_dir.exists()

    restored = client.post(f"/api/undo/{token}")

    assert restored.status_code == 200
    assert restored.json()["kind"] == "delete_graph"
    assert graph_dir.is_dir()


def test_delete_graph_removes_event_rules_and_undo_restores_them(monkeypatch, tmp_path):
    from src.runtime_events.event_config_store import default_event_config

    client = _client(monkeypatch, tmp_path)
    graph_id = f"undo_graph_events_{uuid.uuid4().hex[:8]}"
    node_id = "worker"
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": node_id, "type_id": "missing_node", "graph_id": graph_id},
    )
    assert created.status_code == 200
    events_path = tmp_path / "config" / "events.json"
    events = default_event_config()
    events["rules"] = {
        "OnInput": {
            graph_id: {
                node_id: [
                    {
                        "enabled": True,
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["context.md"], "role": "developer"},
                    }
                ]
            }
        }
    }
    events_path.write_text(json.dumps(events), encoding="utf-8")

    deleted = client.delete(f"/api/graphs/{graph_id}")

    assert deleted.status_code == 200
    assert deleted.json()["removed_event_handlers"] == 1
    assert json.loads(events_path.read_text(encoding="utf-8"))["rules"] == {}

    restored = client.post(f"/api/undo/{deleted.json()['undo_token']}")

    assert restored.status_code == 200
    restored_rules = json.loads(events_path.read_text(encoding="utf-8"))["rules"]
    assert restored_rules["OnInput"][graph_id][node_id][0]["action"] == "context.append_file"


def test_delete_dialogue_can_be_undone(monkeypatch, tmp_path):
    from src.web_backend.node_memory_store import append_node_memory_entry

    client = _client(monkeypatch, tmp_path)
    graph_id = f"undo_message_{uuid.uuid4().hex[:8]}"
    node_id = "speaker"
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": node_id, "type_id": "missing_node", "graph_id": graph_id},
    )
    assert created.status_code == 200
    node_dir = tmp_path / "memories" / graph_id / node_id
    memory_path = str(node_dir / "memory.md")
    messages_path = str(node_dir / "messages.jsonl")
    message_id = "undo-message-1"
    append_node_memory_entry(
        memory_path,
        messages_path,
        "user",
        {"id": message_id, "role": "user", "content": "restore me"},
    )

    deleted = client.delete(
        f"/api/nodes/instances/{node_id}/memory/messages/{message_id}?graph_id={graph_id}"
    )

    assert deleted.status_code == 200
    token = deleted.json().get("undo_token")
    assert token
    assert message_id not in (node_dir / "messages.jsonl").read_text(encoding="utf-8")

    restored = client.post(f"/api/undo/{token}")

    assert restored.status_code == 200
    assert restored.json()["restored"] == 1
    assert message_id in (node_dir / "messages.jsonl").read_text(encoding="utf-8")


def test_delete_dialogue_group_uses_one_undo_step(monkeypatch, tmp_path):
    from src.web_backend.node_memory_store import append_node_memory_entry

    client = _client(monkeypatch, tmp_path)
    graph_id = f"undo_message_group_{uuid.uuid4().hex[:8]}"
    node_id = "speaker"
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": node_id, "type_id": "missing_node", "graph_id": graph_id},
    )
    assert created.status_code == 200
    node_dir = tmp_path / "memories" / graph_id / node_id
    message_ids = ["undo-group-user", "undo-group-assistant"]
    for role, message_id in zip(("user", "assistant"), message_ids):
        append_node_memory_entry(
            str(node_dir / "memory.md"),
            str(node_dir / "messages.jsonl"),
            role,
            {"id": message_id, "role": role, "content": message_id},
        )

    deleted = client.post(
        f"/api/nodes/instances/{node_id}/memory/messages/delete?graph_id={graph_id}",
        json={"message_ids": message_ids},
    )

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 2
    token = deleted.json()["undo_token"]
    restored = client.post(f"/api/undo/{token}")
    assert restored.status_code == 200
    assert restored.json()["restored"] == 2


def test_delete_turn_includes_unloaded_records_and_can_be_undone(monkeypatch, tmp_path):
    from src.web_backend.node_memory_store import append_node_memory_entry

    client = _client(monkeypatch, tmp_path)
    graph_id = f"undo_turn_{uuid.uuid4().hex[:8]}"
    node_id = "speaker"
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": node_id, "type_id": "missing_node", "graph_id": graph_id},
    )
    assert created.status_code == 200
    node_dir = tmp_path / "memories" / graph_id / node_id
    records = [
        ("user", "turn-user", "question"),
        ("assistant_progress", "turn-progress", "hidden progress"),
        ("tool", "turn-tool", "hidden tool"),
        ("assistant", "turn-assistant", "answer"),
        ("metadata", "turn-metadata", "hidden metadata"),
        ("user", "next-user", "next question"),
        ("assistant", "next-assistant", "next answer"),
    ]
    for index, (role, message_id, content) in enumerate(records):
        append_node_memory_entry(
            str(node_dir / "memory.md"),
            str(node_dir / "messages.jsonl"),
            role,
            {
                "id": message_id,
                "role": role,
                "content": content,
                "created_at": f"2026-07-15T00:00:{index:02d}+00:00",
            },
        )

    deleted = client.post(
        f"/api/nodes/instances/{node_id}/memory/turns/delete?graph_id={graph_id}",
        json={"user_message_id": "turn-user"},
    )

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 5
    assert deleted.json()["message_ids"] == [
        "turn-user",
        "turn-progress",
        "turn-tool",
        "turn-assistant",
        "turn-metadata",
    ]
    remaining = (node_dir / "messages.jsonl").read_text(encoding="utf-8")
    assert "turn-user" not in remaining
    assert "turn-metadata" not in remaining
    assert "next-user" in remaining

    restored = client.post(f"/api/undo/{deleted.json()['undo_token']}")

    assert restored.status_code == 200
    assert restored.json()["restored"] == 5
    restored_text = (node_dir / "messages.jsonl").read_text(encoding="utf-8")
    for _role, message_id, _content in records:
        assert message_id in restored_text


def test_undo_retention_uses_configured_max_steps(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    config_path = tmp_path / "config" / "config.json"
    config_path.write_text(json.dumps({"undo": {"maxSteps": 1}}), encoding="utf-8")
    tokens = []
    for index in range(2):
        graph_id = f"undo_retention_{index}_{uuid.uuid4().hex[:6]}"
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": "node", "type_id": "missing_node", "graph_id": graph_id},
        )
        assert created.status_code == 200
        deleted = client.delete(f"/api/nodes/instances/node?graph_id={graph_id}")
        assert deleted.status_code == 200
        tokens.append(deleted.json()["undo_token"])

    assert client.post(f"/api/undo/{tokens[0]}").status_code == 404
    assert client.post(f"/api/undo/{tokens[1]}").status_code == 200
