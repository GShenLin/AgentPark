import json
import os
import shutil
import threading
import uuid


def test_graph_config_strips_nodes_field():
    import src.web_backend as backend

    graph_id = f"ut_strip_nodes_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        graph = {
            "id": graph_id,
            "name": graph_id,
            "nodes": [{"id": "x", "typeId": "append_node", "name": "x", "ui": {"x": 1, "y": 2}}],
            "output_routes": {},
        }
        r = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert r.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, "config.json")
        saved = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert "nodes" not in saved
        assert "links" not in saved
        assert saved.get("output_routes") == {}

        loaded = client.get(f"/api/graphs/{graph_id}").json().get("graph") or {}
        assert "nodes" not in loaded
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_graph_config_persists_working_path():
    import src.web_backend as backend

    graph_id = f"ut_graph_working_path_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        graph = {
            "id": graph_id,
            "name": graph_id,
            "working_path": r"C:\Project\GraphRoot",
            "nodes": [],
            "output_routes": {},
        }
        r = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert r.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, "config.json")
        saved = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert saved.get("working_path") == r"C:\Project\GraphRoot"

        loaded = client.get(f"/api/graphs/{graph_id}").json().get("graph") or {}
        assert loaded.get("working_path") == r"C:\Project\GraphRoot"
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_graph_copy_artifacts_retargets_node_configs_and_skips_runner_log():
    import src.web_backend as backend

    source_graph_id = f"ut_copy_src_{uuid.uuid4().hex[:8]}"
    target_graph_id = f"ut_copy_dst_{uuid.uuid4().hex[:8]}"
    node_id = "Agent"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graphs_dir = _get_graphs_dir()
    source_dir = os.path.join(graphs_dir, source_graph_id)
    target_dir = os.path.join(graphs_dir, target_graph_id)
    try:
        os.makedirs(os.path.join(source_dir, node_id), exist_ok=True)
        with open(os.path.join(source_dir, "config.json"), "w", encoding="utf-8") as handle:
            json.dump({"id": source_graph_id, "name": source_graph_id, "output_routes": {}}, handle)
        with open(os.path.join(source_dir, "runner.events.jsonl"), "w", encoding="utf-8") as handle:
            handle.write('{"event":"old"}\n')
        with open(os.path.join(source_dir, node_id, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "node_id": node_id,
                    "type_id": "agent_node",
                    "name": node_id,
                    "graph_id": source_graph_id,
                },
                handle,
            )

        response = TestClient(app).post(
            f"/api/graphs/{target_graph_id}",
            json={
                "graph": {"id": target_graph_id, "name": target_graph_id, "output_routes": {}},
                "source_graph_id": source_graph_id,
            },
        )

        assert response.status_code == 200
        copied_config_path = os.path.join(target_dir, node_id, "config.json")
        copied_config = json.loads(open(copied_config_path, "r", encoding="utf-8").read())
        assert copied_config["node_id"] == node_id
        assert copied_config["graph_id"] == target_graph_id
        runner_log = os.path.join(target_dir, "runner.events.jsonl")
        if os.path.exists(runner_log):
            assert '{"event":"old"}' not in open(runner_log, "r", encoding="utf-8").read()
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)
        shutil.rmtree(target_dir, ignore_errors=True)


def test_graph_save_without_source_does_not_recopy_default_artifacts_after_node_delete():
    import src.web_backend as backend

    target_graph_id = f"ut_xyj_{uuid.uuid4().hex[:8]}"
    node_id = "GPT2"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    client = TestClient(app)
    graphs_dir = _get_graphs_dir()
    default_node_dir = os.path.join(graphs_dir, "default", node_id)
    target_dir = os.path.join(graphs_dir, target_graph_id)
    target_node_dir = os.path.join(target_dir, node_id)
    default_existed = os.path.exists(default_node_dir)

    try:
        if not default_existed:
            created = client.post(
                "/api/nodes/instances",
                json={"node_id": node_id, "type_id": "append_node", "graph_id": "default"},
            )
            assert created.status_code == 200

        copied = client.post(
            f"/api/graphs/{target_graph_id}",
            json={
                "graph": {"id": target_graph_id, "name": target_graph_id, "output_routes": {}},
                "source_graph_id": "default",
            },
        )
        assert copied.status_code == 200
        assert os.path.isdir(target_node_dir)

        deleted = client.delete(f"/api/nodes/instances/{node_id}?graph_id={target_graph_id}")
        assert deleted.status_code == 200
        assert not os.path.exists(target_node_dir)
        assert os.path.isdir(default_node_dir)

        saved = client.post(
            f"/api/graphs/{target_graph_id}",
            json={"graph": {"id": target_graph_id, "name": target_graph_id, "output_routes": {}}},
        )
        assert saved.status_code == 200
        assert not os.path.exists(target_node_dir)
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)
        if not default_existed:
            shutil.rmtree(default_node_dir, ignore_errors=True)


def test_graph_load_supports_version_unchanged_response():
    import src.web_backend as backend

    graph_id = f"ut_graph_version_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        graph = {
            "id": graph_id,
            "name": graph_id,
            "nodes": [],
            "output_routes": {"a": [{"output_index": 0, "targets": [{"node_id": "b", "input_index": 0}]}]},
        }
        r = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert r.status_code == 200

        loaded = client.get(f"/api/graphs/{graph_id}")
        assert loaded.status_code == 200
        payload = loaded.json().get("graph") or {}
        version = int(payload.get("version") or 0)
        assert version > 0
        assert payload.get("output_routes")

        unchanged = client.get(f"/api/graphs/{graph_id}?if_version={version}")
        assert unchanged.status_code == 200
        unchanged_payload = unchanged.json().get("graph") or {}
        assert unchanged_payload == {"id": graph_id, "version": version, "unchanged": True}
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_graph_config_drops_links_without_conversion():
    import src.web_backend as backend

    graph_id = f"ut_drop_links_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        graph = {
            "id": graph_id,
            "name": graph_id,
            "nodes": [
                {"id": "source", "typeId": "append_node", "name": "source", "ui": {"x": 0, "y": 0}},
                {"id": "target", "typeId": "append_node", "name": "target", "ui": {"x": 100, "y": 0}},
            ],
            "links": [{"id": "old", "from": {"node": "source", "index": 0}, "to": {"node": "target", "index": 0}}],
        }
        response = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert response.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, "config.json")
        saved = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert "links" not in saved
        assert saved.get("output_routes") == {}
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_node_rename_and_delete_keep_output_routes_consistent():
    import src.web_backend as backend

    graph_id = f"ut_routes_consistency_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    client = TestClient(app)
    try:
        for node_id in ("source", "target"):
            created = client.post(
                "/api/nodes/instances",
                json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id},
            )
            assert created.status_code == 200

        saved = client.post(
            f"/api/graphs/{graph_id}",
            json={
                "graph": {
                    "id": graph_id,
                    "name": graph_id,
                    "output_routes": {
                        "source": [
                            {
                                "output_index": 0,
                                "targets": [{"node_id": "target", "input_index": 0}],
                            }
                        ]
                    },
                }
            },
        )
        assert saved.status_code == 200

        renamed = client.post(
            f"/api/nodes/instances/source/rename?graph_id={graph_id}",
            json={"new_node_id": "renamed", "new_name": "renamed"},
        )
        assert renamed.status_code == 200
        after_rename = json.loads(open(os.path.join(graph_dir, "config.json"), "r", encoding="utf-8").read())
        assert "source" not in after_rename["output_routes"]
        assert after_rename["output_routes"]["renamed"][0]["targets"][0]["node_id"] == "target"

        deleted = client.delete(f"/api/nodes/instances/target?graph_id={graph_id}")
        assert deleted.status_code == 200
        after_delete = json.loads(open(os.path.join(graph_dir, "config.json"), "r", encoding="utf-8").read())
        assert after_delete["output_routes"]["renamed"][0]["targets"] == []
        assert "links" not in after_delete
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_graph_load_rejects_non_object_config():
    import src.web_backend as backend

    graph_id = f"ut_graph_bad_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        os.makedirs(graph_dir, exist_ok=True)
        with open(os.path.join(graph_dir, "config.json"), "w", encoding="utf-8") as handle:
            handle.write("[]")

        response = TestClient(app).get(f"/api/graphs/{graph_id}")

        assert response.status_code == 500
        assert "JSON object" in response.json().get("detail", "")
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_graph_list_includes_companion_and_marks_protected_graphs_readonly(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.web_backend import runtime_paths
    import src.web_backend as backend

    graphs_dir = tmp_path / "memories"
    for graph_id, name in (("default", "default"), ("Companion", "Companion"), ("work", "Work")):
        graph_dir = graphs_dir / graph_id
        graph_dir.mkdir(parents=True)
        with open(graph_dir / "config.json", "w", encoding="utf-8") as handle:
            json.dump({"id": graph_id, "name": name, "output_routes": {}}, handle)
    companion_node_dir = graphs_dir / "Companion" / "Companion"
    companion_node_dir.mkdir()
    with open(companion_node_dir / "config.json", "w", encoding="utf-8") as handle:
        json.dump({"graph_id": "Companion", "node_id": "Companion", "type_id": "agent_node"}, handle)
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    response = TestClient(backend.create_app()).get("/api/graphs")

    assert response.status_code == 200
    graphs = {item["id"]: item for item in response.json()["graphs"]}
    assert {"default", "Companion", "work"}.issubset(graphs)
    assert graphs["default"]["readonly"] is True
    assert graphs["default"]["deletable"] is False
    assert graphs["default"]["editable"] is True
    assert graphs["Companion"]["readonly"] is True
    assert graphs["Companion"]["deletable"] is False
    assert graphs["Companion"]["editable"] is True
    assert graphs["work"].get("readonly") is False
    assert graphs["work"]["deletable"] is True
    assert graphs["work"]["editable"] is True


def test_companion_graph_load_uses_normal_graph_and_node_layout(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.web_backend import runtime_paths
    import src.web_backend as backend

    graphs_dir = tmp_path / "memories"
    companion_graph_dir = graphs_dir / "Companion"
    companion_node_dir = companion_graph_dir / "Companion"
    companion_node_dir.mkdir(parents=True)
    graph_config = {"id": "Companion", "name": "Companion", "working_path": "", "output_routes": {}}
    node_config = {
        "graph_id": "Companion",
        "node_id": "Companion",
        "type_id": "agent_node",
        "name": "Companion",
        "provider_id": "provider-a",
        "mode": "chat",
        "tools": ["system_tools"],
    }
    with open(companion_graph_dir / "config.json", "w", encoding="utf-8") as handle:
        json.dump(graph_config, handle)
    with open(companion_node_dir / "config.json", "w", encoding="utf-8") as handle:
        json.dump(node_config, handle)
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    client = TestClient(backend.create_app())
    response = client.get("/api/graphs/Companion")

    assert response.status_code == 200
    graph = response.json()["graph"]
    assert graph["id"] == "Companion"
    assert graph["output_routes"] == {}
    saved_graph = json.loads((companion_graph_dir / "config.json").read_text(encoding="utf-8"))
    saved_node = json.loads((companion_node_dir / "config.json").read_text(encoding="utf-8"))
    assert saved_graph == graph_config
    assert saved_node == node_config


def test_companion_node_configs_use_normal_node_layout(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.web_backend import runtime_paths
    import src.web_backend as backend

    graphs_dir = tmp_path / "memories"
    companion_node_dir = graphs_dir / "Companion" / "Companion"
    companion_node_dir.mkdir(parents=True)
    with open(graphs_dir / "Companion" / "config.json", "w", encoding="utf-8") as handle:
        json.dump({"id": "Companion", "name": "Companion", "output_routes": {}}, handle)
    with open(companion_node_dir / "config.json", "w", encoding="utf-8") as handle:
        json.dump({"graph_id": "Companion", "node_id": "Companion", "type_id": "agent_node", "name": "Companion"}, handle)
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    response = TestClient(backend.create_app()).get("/api/nodes/instances/configs?graph_id=Companion")

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_ids"] == ["Companion"]
    assert payload["nodes"][0]["node_id"] == "Companion"
    assert payload["nodes"][0]["graph_id"] == "Companion"


def test_delete_graph_rejects_protected_graphs(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.web_backend import runtime_paths
    import src.web_backend as backend

    graphs_dir = tmp_path / "memories"
    graphs_dir.mkdir()
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    client = TestClient(backend.create_app())

    for graph_id in ("default", "Companion"):
        response = client.delete(f"/api/graphs/{graph_id}")
        assert response.status_code == 403
        assert "protected graph cannot be deleted" in response.json().get("detail", "")


def test_delete_graph_stops_runner_before_removing_runner_log():
    import src.web_backend as backend

    graph_id = f"ut_delete_runner_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        client = TestClient(app)
        saved = client.post(f"/api/graphs/{graph_id}", json={"graph": {"id": graph_id, "name": graph_id, "output_routes": {}}})
        assert saved.status_code == 200
        started = client.post(f"/api/graphs/{graph_id}/runner/start")
        assert started.status_code == 200

        deleted = client.delete(f"/api/graphs/{graph_id}?wait_timeout_seconds=2")

        assert deleted.status_code == 200
        assert deleted.json().get("deleted") is True
        assert not os.path.exists(graph_dir)
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_delete_graph_resets_startup_graph_when_it_points_to_deleted_graph(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src import workspace_settings
    from src.web_backend import runtime_paths
    import src.web_backend as backend

    runtime_root = tmp_path / "workspace"
    graphs_dir = runtime_root / "memories"
    graph_id = "delete_startup_target"
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(runtime_root))

    client = TestClient(backend.create_app())
    saved = client.post(
        f"/api/graphs/{graph_id}",
        json={"graph": {"id": graph_id, "name": "Delete Startup Target", "output_routes": {}}},
    )
    assert saved.status_code == 200
    startup = client.post(
        "/api/graphs/startup/config",
        json={"graph_id": graph_id, "graph_name": "Delete Startup Target"},
    )
    assert startup.status_code == 200

    deleted = client.delete(f"/api/graphs/{graph_id}")

    assert deleted.status_code == 200
    assert deleted.json().get("deleted") is True
    assert client.get("/api/graphs/startup/config").json() == {
        "graph_id": "default",
        "graph_name": "default",
    }
    startup_cache = json.loads((runtime_root / ".cache" / "startup_graph.json").read_text(encoding="utf-8"))
    assert startup_cache == {"graph_id": "default", "graph_name": "default"}


def test_delete_graph_reports_runner_stop_timeout():
    import src.web_backend as backend

    graph_id = f"ut_delete_blocked_{uuid.uuid4().hex[:8]}"
    facade = backend.WebBackendFacade()
    app = facade.build()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    stop_event = threading.Event()
    wake_event = threading.Event()
    blocker = threading.Thread(target=lambda: stop_event.wait(timeout=30), daemon=True)
    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        client = TestClient(app)
        saved = client.post(f"/api/graphs/{graph_id}", json={"graph": {"id": graph_id, "name": graph_id, "output_routes": {}}})
        assert saved.status_code == 200
        blocker.start()
        facade.core.graph_runners[graph_id] = {
            "threads": [blocker],
            "stop": threading.Event(),
            "wake": wake_event,
            "worker_count": 1,
        }

        deleted = client.delete(f"/api/graphs/{graph_id}?wait_timeout_seconds=0.01")

        assert deleted.status_code == 409
        assert "graph runner did not stop" in deleted.json().get("detail", "")
        assert os.path.exists(graph_dir)
    finally:
        stop_event.set()
        blocker.join(timeout=1)
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_delete_graph_reports_active_executor_task_timeout():
    import src.web_backend as backend
    from src.web_backend.graph_runner_state import GraphExecutor, GraphRunnerState

    graph_id = f"ut_delete_active_{uuid.uuid4().hex[:8]}"
    facade = backend.WebBackendFacade()
    app = facade.build()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    release = threading.Event()
    runner_state = GraphRunnerState(
        scheduler_thread=None,
        stop=threading.Event(),
        wake=threading.Event(),
        executor=GraphExecutor(graph_id),
    )
    task = runner_state.executor.submit(
        task_id="trace-active:n1",
        node_id="n1",
        trace_id="trace-active",
        func=lambda: release.wait(timeout=30),
    )
    runner_state.active_tasks[task.task_id] = task
    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        client = TestClient(app)
        saved = client.post(f"/api/graphs/{graph_id}", json={"graph": {"id": graph_id, "name": graph_id, "output_routes": {}}})
        assert saved.status_code == 200
        facade.core.graph_runners[graph_id] = runner_state

        deleted = client.delete(f"/api/graphs/{graph_id}?wait_timeout_seconds=0.01")

        assert deleted.status_code == 409
        assert "graph runner did not stop" in deleted.json().get("detail", "")
        assert os.path.exists(graph_dir)
    finally:
        release.set()
        task.thread.join(timeout=1)
        with facade.core.graph_runners_lock:
            facade.core.graph_runners.pop(graph_id, None)
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_graph_list_rejects_corrupt_config():
    import src.web_backend as backend

    graph_id = f"ut_graph_list_bad_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        os.makedirs(graph_dir, exist_ok=True)
        with open(os.path.join(graph_dir, "config.json"), "w", encoding="utf-8") as handle:
            handle.write("{bad")

        response = TestClient(app).get("/api/graphs")

        assert response.status_code == 500
        assert "invalid JSON" in response.json().get("detail", "")
        assert graph_id in response.json().get("detail", "")
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_runtime_graph_read_rejects_non_object_config(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.graph_runtime_registry import GraphConfigReadError

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    graph_dir = tmp_path / "memories" / "bad_graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "config.json").write_text("[]", encoding="utf-8")

    runtime = backend.WebBackendFacade().core.graph_runtime

    try:
        runtime._read_graph_config("bad_graph")
    except GraphConfigReadError as exc:
        assert "JSON object" in str(exc)
    else:
        raise AssertionError("non-object graph config was not rejected")
