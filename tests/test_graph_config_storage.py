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
            "links": [],
        }
        r = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert r.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, "config.json")
        saved = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert "nodes" not in saved
        assert saved.get("links") == []

        loaded = client.get(f"/api/graphs/{graph_id}").json().get("graph") or {}
        assert "nodes" not in loaded
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
            json.dump({"id": source_graph_id, "name": source_graph_id, "links": []}, handle)
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
                "graph": {"id": target_graph_id, "name": target_graph_id, "links": []},
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
                "graph": {"id": target_graph_id, "name": target_graph_id, "links": []},
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
            json={"graph": {"id": target_graph_id, "name": target_graph_id, "links": []}},
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
            "links": [{"id": "l1", "from": {"node": "a", "index": 0}, "to": {"node": "b", "index": 0}}],
        }
        r = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert r.status_code == 200

        loaded = client.get(f"/api/graphs/{graph_id}")
        assert loaded.status_code == 200
        payload = loaded.json().get("graph") or {}
        version = int(payload.get("version") or 0)
        assert version > 0
        assert payload.get("links")

        unchanged = client.get(f"/api/graphs/{graph_id}?if_version={version}")
        assert unchanged.status_code == 200
        unchanged_payload = unchanged.json().get("graph") or {}
        assert unchanged_payload == {"id": graph_id, "version": version, "unchanged": True}
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


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


def test_delete_graph_stops_runner_before_removing_runner_log():
    import src.web_backend as backend

    graph_id = f"ut_delete_runner_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        client = TestClient(app)
        saved = client.post(f"/api/graphs/{graph_id}", json={"graph": {"id": graph_id, "name": graph_id, "links": []}})
        assert saved.status_code == 200
        started = client.post(f"/api/graphs/{graph_id}/runner/start")
        assert started.status_code == 200

        deleted = client.delete(f"/api/graphs/{graph_id}?wait_timeout_seconds=2")

        assert deleted.status_code == 200
        assert deleted.json().get("deleted") is True
        assert not os.path.exists(graph_dir)
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


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
        saved = client.post(f"/api/graphs/{graph_id}", json={"graph": {"id": graph_id, "name": graph_id, "links": []}})
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
        saved = client.post(f"/api/graphs/{graph_id}", json={"graph": {"id": graph_id, "name": graph_id, "links": []}})
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
