import json
import os
import shutil
import threading
import uuid

from src.web_backend.node_config_service import node_runtime_state_path


def test_clone_node_instance_copies_artifacts_and_resets_runtime_state():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_clone_{uuid.uuid4().hex[:8]}"
    node_id = "source_node"
    clone_id = "clone1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        source_dir = os.path.join(_get_graphs_dir(), graph_id, node_id)
        config_path = os.path.join(source_dir, "config.json")
        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        payload.update(
            {
                "custom_field": "kept",
                "state": "working",
                "pending": [{"id": "queued"}],
                "pending_count": 1,
                "inflight": {"id": "running"},
                "_stop_requested": True,
                "last_runtime_event": {"event": "running"},
                "runtime_events": [{"event": "running"}],
                "runtime_tool_calls": [{"tool": "x"}],
                "last_message": "latest copied preview",
                "ui": {"x": 9, "y": 10},
            }
        )
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        with open(os.path.join(source_dir, f"{node_id}.md"), "w", encoding="utf-8") as f:
            f.write("copied memory")
        with open(os.path.join(source_dir, f"{node_id}_artifact.txt"), "w", encoding="utf-8") as f:
            f.write("copied artifact")

        cloned = client.post(
            f"/api/nodes/instances/{node_id}/clone?graph_id={graph_id}",
            json={"new_node_id": clone_id, "new_name": "Clone 1", "ui": {"x": 44, "y": 55}},
        )
        assert cloned.status_code == 200
        assert cloned.json().get("source_node_id") == node_id
        assert cloned.json().get("node_id") == clone_id

        clone_dir = os.path.join(_get_graphs_dir(), graph_id, clone_id)
        assert os.path.isdir(clone_dir)
        assert not os.path.exists(os.path.join(clone_dir, f"{node_id}.md"))
        assert not os.path.exists(os.path.join(clone_dir, f"{node_id}_artifact.txt"))
        assert open(os.path.join(clone_dir, f"{clone_id}.md"), "r", encoding="utf-8").read() == "copied memory"
        assert open(os.path.join(clone_dir, f"{clone_id}_artifact.txt"), "r", encoding="utf-8").read() == "copied artifact"

        clone_cfg = json.loads(open(os.path.join(clone_dir, "config.json"), "r", encoding="utf-8").read())
        assert clone_cfg.get("node_id") == clone_id
        assert clone_cfg.get("graph_id") == graph_id
        assert clone_cfg.get("name") == "Clone 1"
        assert clone_cfg.get("ui") == {"x": 44, "y": 55}
        assert clone_cfg.get("custom_field") == "kept"
        for key in (
            "state",
            "pending",
            "pending_count",
            "inflight",
            "_stop_requested",
            "last_runtime_event",
            "runtime_events",
            "runtime_tool_calls",
            "last_message",
        ):
            assert key not in clone_cfg
        clone_runtime = json.loads(open(node_runtime_state_path(os.path.join(clone_dir, "config.json")), "r", encoding="utf-8").read())
        assert clone_runtime == {"state": "idle"}
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_rename_node_instance_preserves_runtime_state_in_runtime_file():
    import src.web_backend as backend
    from src.web_backend.node_config_service import node_config_service
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_rename_runtime_{uuid.uuid4().hex[:8]}"
    node_id = "source_node"
    renamed_id = "renamed_node"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id},
        )
        assert created.status_code == 200

        source_dir = os.path.join(_get_graphs_dir(), graph_id, node_id)
        source_config_path = os.path.join(source_dir, "config.json")
        merged = node_config_service.read_strict(source_config_path)
        merged.update(
            {
                "state": "working",
                "pending": [{"id": "queued"}],
                "pending_count": 1,
                "last_message": "runtime preview",
                "node_event_seq": 3,
            }
        )
        node_config_service.write(source_config_path, merged)

        renamed = client.post(
            f"/api/nodes/instances/{node_id}/rename?graph_id={graph_id}",
            json={"new_node_id": renamed_id, "new_name": "Renamed"},
        )
        assert renamed.status_code == 200

        renamed_dir = os.path.join(_get_graphs_dir(), graph_id, renamed_id)
        renamed_config_path = os.path.join(renamed_dir, "config.json")
        assert not os.path.exists(source_dir)
        assert os.path.exists(node_runtime_state_path(renamed_config_path))

        raw_config = json.loads(open(renamed_config_path, "r", encoding="utf-8").read())
        runtime_state = json.loads(open(node_runtime_state_path(renamed_config_path), "r", encoding="utf-8").read())
        merged_after = node_config_service.read_strict(renamed_config_path)
        for key in ("state", "pending", "pending_count", "last_message", "node_event_seq"):
            assert key not in raw_config
        assert raw_config["node_id"] == renamed_id
        assert runtime_state["state"] == "working"
        assert runtime_state["pending_count"] == 1
        assert runtime_state["last_message"] == "runtime preview"
        assert merged_after["node_id"] == renamed_id
        assert merged_after["last_message"] == "runtime preview"
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_update_node_instance_config_persists_ui():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_ui_{uuid.uuid4().hex[:8]}"
    node_id = "n1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        r = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert r.status_code == 200

        r = client.post(
            f"/api/nodes/instances/{node_id}/config?graph_id={graph_id}",
            json={"ui": {"x": 321, "y": 654}},
        )
        assert r.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        ui = payload.get("ui") if isinstance(payload, dict) else None
        assert isinstance(ui, dict)
        assert ui.get("x") == 321
        assert ui.get("y") == 654
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_list_node_instance_configs_supports_incremental_refresh():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_incremental_{uuid.uuid4().hex[:8]}"
    node_id = "n1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        first = client.get(f"/api/nodes/instances/configs?graph_id={graph_id}")
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["partial"] is False
        assert first_payload["node_ids"] == [node_id]
        assert first_payload["nodes"][0]["node_id"] == node_id
        version = int(first_payload["version"])
        assert version > 0

        unchanged = client.get(f"/api/nodes/instances/configs?graph_id={graph_id}&since_version={version}")
        assert unchanged.status_code == 200
        unchanged_payload = unchanged.json()
        assert unchanged_payload["partial"] is True
        assert unchanged_payload["node_ids"] == [node_id]
        assert unchanged_payload["nodes"] == []

        updated = client.post(
            f"/api/nodes/instances/{node_id}/config?graph_id={graph_id}",
            json={"fields": {"custom_field": "changed"}},
        )
        assert updated.status_code == 200
        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        os.utime(config_path, None)

        changed = client.get(f"/api/nodes/instances/configs?graph_id={graph_id}&since_version={version}")
        assert changed.status_code == 200
        changed_payload = changed.json()
        assert changed_payload["partial"] is True
        assert [item["node_id"] for item in changed_payload["nodes"]] == [node_id]
        assert changed_payload["nodes"][0]["custom_field"] == "changed"
        assert int(changed_payload["version"]) > version
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_list_node_instance_configs_migrates_missing_working_path():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_working_path_{uuid.uuid4().hex[:8]}"
    node_id = "legacy_node"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        payload.pop("working_path", None)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        response = client.get(f"/api/nodes/instances/configs?graph_id={graph_id}")
        assert response.status_code == 200
        nodes = response.json().get("nodes") or []
        cfg = next(item for item in nodes if str(item.get("node_id") or "") == node_id)
        assert cfg.get("working_path") == ""

        saved = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert saved.get("working_path") == ""
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_update_node_instance_config_recomputes_dynamic_input_ports():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_ports_{uuid.uuid4().hex[:8]}"
    node_id = "multi1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "multi_input_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        created_cfg = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert created_cfg.get("input_num") == 2

        updated = client.post(
            f"/api/nodes/instances/{node_id}/config?graph_id={graph_id}",
            json={"fields": {"InputCount": "3"}},
        )
        assert updated.status_code == 200

        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert payload.get("InputCount") == "3"
        assert payload.get("input_num") == 3
        assert payload.get("output_num") == 1
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_update_node_instance_config_rejects_corrupt_config():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_bad_apply_{uuid.uuid4().hex[:8]}"
    node_id = "n1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id},
        )
        assert created.status_code == 200
        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("{bad")

        response = client.post(
            f"/api/nodes/instances/{node_id}/config?graph_id={graph_id}",
            json={"fields": {"Custom": "value"}},
        )

        assert response.status_code == 500
        assert "invalid JSON" in response.json().get("detail", "")
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_list_node_instance_configs_rejects_non_object_config():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_bad_list_{uuid.uuid4().hex[:8]}"
    node_id = "n1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id},
        )
        assert created.status_code == 200
        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("[]")

        response = client.get(f"/api/nodes/instances/configs?graph_id={graph_id}")

        assert response.status_code == 500
        assert "JSON object" in response.json().get("detail", "")
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_create_loop_node_instance_persists_two_output_ports():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_loop_ports_{uuid.uuid4().hex[:8]}"
    node_id = "loop1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "loop_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert payload.get("LoopCount") == "1"
        assert payload.get("input_num") == 1
        assert payload.get("output_num") == 2
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_get_node_instance_memory_returns_empty_payload_before_any_history_exists():
    import src.web_backend as backend

    graph_id = f"ut_empty_memory_{uuid.uuid4().hex[:8]}"
    node_id = "empty_node"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        response = client.get(f"/api/nodes/instances/{node_id}/memory?graph_id={graph_id}&max_chars=20000")
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("text") == ""
        assert payload.get("messages") == []
        assert payload.get("state") == "idle"
        assert payload.get("last_message") == ""
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_clear_node_instance_memory_resets_visible_runtime_summary():
    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src.web_backend.node_memory_store import append_node_memory_entry
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_clear_memory_{uuid.uuid4().hex[:8]}"
    node_id = "clear_node"
    facade = backend.WebBackendFacade()
    app = facade.build()

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "agent_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        cfg.update(
            {
                "last_message": "old answer",
                "last_run_at": "2026-06-26 18:00:00",
                "last_runtime_event": {"type": "tool_call_end", "error": "old error"},
                "runtime_events": [{"type": "runtime_notice"}],
                "runtime_tool_calls": [{"name": "read_file", "status": "completed"}],
                "node_event_seq": 4,
            }
        )
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, ensure_ascii=False, indent=2)

        memory_path = facade.core.graph_runtime._node_memory_path(node_id, graph_id)
        messages_path = facade.core.graph_runtime._node_messages_path(node_id, graph_id)
        append_node_memory_entry(memory_path, messages_path, "user", "old question")
        facade.core.node_live_outputs.update(graph_id, node_id, "old live")

        response = client.post(f"/api/nodes/instances/{node_id}/clear-memory?graph_id={graph_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert "last_message" in body["cleared_summary_fields"]

        memory = client.get(f"/api/nodes/instances/{node_id}/memory?graph_id={graph_id}&max_chars=20000").json()
        assert memory["text"] == ""
        assert memory["messages"] == []
        assert memory["last_message"] == ""
        assert memory["live_message"] == ""

        with open(config_path, "r", encoding="utf-8") as handle:
            cleared = json.load(handle)
        for key in ("last_message", "node_event_seq", "last_run_at", "last_runtime_event", "runtime_events", "runtime_tool_calls"):
            assert key not in cleared
        with open(node_runtime_state_path(config_path), "r", encoding="utf-8") as handle:
            cleared_runtime = json.load(handle)
        assert cleared_runtime["last_message"] == ""
        assert cleared_runtime["node_event_seq"] > 4
        for key in ("last_run_at", "last_runtime_event", "runtime_events", "runtime_tool_calls"):
            assert key not in cleared_runtime
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_get_node_template_reports_metadata_load_errors(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    broken_node = nodes_dir / "broken_template_node.py"
    broken_node.write_text("raise RuntimeError('template boom')\n", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_nodes_dir", lambda: str(nodes_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_resource_root", lambda: str(tmp_path))

    app = backend.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.get("/api/nodes/templates/broken_template_node")

    assert response.status_code == 500
    assert "Error loading node module" in response.json().get("detail", "")


def test_create_node_instance_reports_on_create_metadata_errors(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    node_source = """
class Node:
    def on_create(self, config, context):
        raise RuntimeError('on create boom')
"""
    (nodes_dir / "bad_create_node.py").write_text(node_source, encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_nodes_dir", lambda: str(nodes_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_resource_root", lambda: str(tmp_path))

    app = backend.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/api/nodes/instances",
        json={"node_id": "bad_create", "type_id": "bad_create_node", "graph_id": "ut_bad_create"},
    )

    assert response.status_code == 500
    assert "on create boom" in response.json().get("detail", "")


def test_delete_node_instance_reports_delete_failures(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    app = backend.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": "delete_fail", "type_id": "missing_node", "graph_id": "ut_delete_fail"},
    )
    assert created.status_code == 200

    def fail_rmtree(_path):
        raise OSError("delete boom")

    monkeypatch.setattr(shutil, "rmtree", fail_rmtree)
    response = client.delete("/api/nodes/instances/delete_fail?graph_id=ut_delete_fail")

    assert response.status_code == 500
    assert "delete boom" in response.json().get("detail", "")


def test_delete_node_instance_waits_for_active_cancellation(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    facade = backend.WebBackendFacade()
    app = facade.build()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": "delete_active", "type_id": "missing_node", "graph_id": "ut_delete_active"},
    )
    assert created.status_code == 200

    config_path = os.path.join(tmp_path, "memories", "ut_delete_active", "delete_active", "config.json")
    node_dir = os.path.dirname(config_path)
    cancel_event = facade.core.node_cancellations.begin(config_path)
    response_holder = {}

    def delete_node():
        response_holder["response"] = client.delete(
            "/api/nodes/instances/delete_active?graph_id=ut_delete_active&wait_timeout_seconds=2"
        )

    thread = threading.Thread(target=delete_node)
    thread.start()
    try:
        assert cancel_event.wait(timeout=1)
        facade.core.node_cancellations.end(config_path, cancel_event)
        thread.join(timeout=2)
    finally:
        if thread.is_alive():
            facade.core.node_cancellations.end(config_path, cancel_event)
            thread.join(timeout=2)

    response = response_holder.get("response")
    assert response is not None
    assert response.status_code == 200
    assert response.json().get("active_cancelled") == 1
    assert not os.path.exists(node_dir)


def test_delete_node_instance_reports_active_timeout(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    facade = backend.WebBackendFacade()
    app = facade.build()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": "delete_busy", "type_id": "missing_node", "graph_id": "ut_delete_busy"},
    )
    assert created.status_code == 200

    config_path = os.path.join(tmp_path, "memories", "ut_delete_busy", "delete_busy", "config.json")
    node_dir = os.path.dirname(config_path)
    cancel_event = facade.core.node_cancellations.begin(config_path)
    try:
        response = client.delete(
            "/api/nodes/instances/delete_busy?graph_id=ut_delete_busy&wait_timeout_seconds=0.01"
        )
    finally:
        facade.core.node_cancellations.end(config_path, cancel_event)

    assert response.status_code == 409
    assert "active task" in response.json().get("detail", "")
    assert os.path.isdir(node_dir)


def test_delete_node_instance_stops_async_run(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.joined = False
            self.alive = True

        def terminate(self):
            self.terminated = True

        def join(self, timeout=None):
            self.joined = True
            self.alive = False

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    facade = backend.WebBackendFacade()
    app = facade.build()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": "delete_async", "type_id": "missing_node", "graph_id": "ut_delete_async"},
    )
    assert created.status_code == 200

    config_path = os.path.join(tmp_path, "memories", "ut_delete_async", "delete_async", "config.json")
    process = FakeProcess()
    facade.core.node_runs["run-1"] = {
        "process": process,
        "status": "running",
        "node_config_path": config_path,
    }

    response = client.delete("/api/nodes/instances/delete_async?graph_id=ut_delete_async")

    assert response.status_code == 200
    assert response.json().get("stopped_runs") == 1
    assert process.terminated
    assert process.joined
    assert facade.core.node_runs["run-1"]["status"] == "stopped"
    assert not os.path.exists(os.path.dirname(config_path))


def test_enqueue_pending_rejects_node_being_deleted(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.shared import _mark_node_delete_requested

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    app = backend.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": "delete_pending", "type_id": "missing_node", "graph_id": "ut_delete_pending"},
    )
    assert created.status_code == 200

    config_path = os.path.join(tmp_path, "memories", "ut_delete_pending", "delete_pending", "config.json")
    _mark_node_delete_requested(config_path)
    response = client.post(
        "/api/nodes/instances/delete_pending/pending?graph_id=ut_delete_pending",
        json={"payload": "hello"},
    )

    assert response.status_code == 409
    assert "being deleted" in response.json().get("detail", "")
