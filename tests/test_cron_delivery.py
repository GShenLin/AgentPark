import json
import threading

import pytest

from src.cron.repository import CronRepository
from src.cron.schedule import CreateJob, UpdateJob
from src.message_protocol import build_text_envelope, envelope_text
from src.web_backend.core import BackendCore
from src.web_backend.cron_service import CronService
from src.web_backend.runtime_state_memory_store import runtime_state_memory_store
from src.web_backend.state_store import _dequeue_node_pending_to_working, _read_json_dict


@pytest.fixture
def setup_node(tmp_path, monkeypatch):
    graph = tmp_path / "memories" / "default"
    node = graph / "agent"
    node.mkdir(parents=True)
    config_path = node / "config.json"
    config_path.write_text(json.dumps({"node_id": "agent", "type_id": "agent_node", "graph_id": "default"}), encoding="utf-8")
    core = BackendCore()
    monkeypatch.setattr(core.graph_runtime, "_ensure_graph_runner", lambda _: None)
    monkeypatch.setattr(core.graph_runtime, "_wake_graph_runner", lambda _: None)
    monkeypatch.setattr(core.graph_runtime, "_emit_runtime_event", lambda **kw: None)
    repo = CronRepository(graph)
    job = repo.create("agent", CreateJob(name="check", prompt="Original prompt",
        schedule={"kind": "every", "seconds": 60}), "nondeveloper", 1000)
    return core, repo, job, config_path


def execute(core, config, pending):
    core.graph_runtime._run_single_node_iteration(safe_graph_id="default", entry="agent", cfg={},
        config_path=str(config), pending_item=pending, outgoing={}, nodes_dir="nodes", wake_event=threading.Event())


def test_delivery_survives_memory_queue_loss_and_executes_once(setup_node, monkeypatch):
    core, repo, job, config = setup_node
    core.cron_service.poll_graph(config.parent.parent, now=1060)
    core.cron_service.poll_graph(config.parent.parent, now=1061)
    assert len(_read_json_dict(str(config))["pending"]) == 1
    run_id = repo.pending_runs()[0]["id"]
    runtime_state_memory_store.replace(str(config), {})
    restarted = CronService(core)
    restarted.poll_graph(config.parent.parent, now=1062)
    pending = _dequeue_node_pending_to_working(str(config))
    assert pending["trace_id"] == run_id
    repo.update("agent", UpdateJob(job_id=job["id"], expected_revision=1, prompt="Updated prompt"), "developer", 1062)
    observed = []

    def fake_run(nodes, kind, message, context):
        observed.append((envelope_text(message), context["access_role"]))
        return {"message": build_text_envelope("done", role="assistant"), "routes": []}

    monkeypatch.setattr("src.web_backend.graph_node_execution._run_node_logic_with_routes", fake_run)
    execute(core, config, pending)
    assert len(observed) == 1
    assert "Updated prompt" in observed[0][0]
    assert observed[0][1] == "nondeveloper"
    assert repo.list("agent")["recent_runs"][0]["status"] == "completed"
    restarted.poll_graph(config.parent.parent, now=1063)
    assert not _read_json_dict(str(config))["pending"]
    execute(core, config, pending)
    assert len(observed) == 1


def test_paused_queued_run_never_calls_model(setup_node, monkeypatch):
    core, repo, job, config = setup_node
    core.cron_service.poll_graph(config.parent.parent, now=1060)
    repo.update("agent", UpdateJob(job_id=job["id"], expected_revision=1, enabled=False), "developer", 1060)
    monkeypatch.setattr("src.web_backend.graph_node_execution._run_node_logic_with_routes",
                        lambda *a: pytest.fail("Cancelled schedule executed"))
    execute(core, config, _dequeue_node_pending_to_working(str(config)))
    assert _read_json_dict(str(config)).get("inflight") is None
    assert repo.list("agent")["recent_runs"][0]["status"] == "cancelled"


def test_execution_error_is_visible_without_immediate_retry(setup_node, monkeypatch):
    core, repo, job, config = setup_node
    core.cron_service.poll_graph(config.parent.parent, now=1060)

    def fail(*args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("src.web_backend.graph_node_execution._run_node_logic_with_routes", fail)
    execute(core, config, _dequeue_node_pending_to_working(str(config)))
    run = repo.list("agent")["recent_runs"][0]
    assert run["status"] == "failed"
    assert "provider unavailable" in run["error"]
    assert repo.pending_runs() == []


def test_enqueue_failure_retains_outbox_and_error(setup_node, monkeypatch):
    core, repo, job, config = setup_node

    def fail(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("src.web_backend.node_instance_queue.NodeInstanceQueue.enqueue_node_instance_pending", fail)
    core.cron_service.poll_graph(config.parent.parent, now=1060)
    assert repo.pending_runs()[0]["error"] == "RuntimeError: queue unavailable"


def test_service_start_recovers_interrupted_run(setup_node, monkeypatch):
    core, repo, job, config = setup_node
    repo.materialize_due(1060)
    run = repo.pending_runs()[0]
    repo.begin_run(run["id"], "agent", 1060)
    monkeypatch.setattr(core.cron_service, "_run", lambda: None)
    core.cron_service.start()
    core.cron_service.close()
    assert repo.pending_runs()[0]["id"] == run["id"]
