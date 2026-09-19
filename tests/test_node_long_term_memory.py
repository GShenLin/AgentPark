from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.long_term_memory.contracts import Consolidation, MemoryContractError, encode
from src.long_term_memory.jobs import PipelineLease
from src.long_term_memory.pipeline import MemoryPipeline
from src.long_term_memory.retrieval import MemoryReader
from src.long_term_memory.settings import MemorySettings
from src.long_term_memory.sources import load_sources
from src.long_term_memory.store import MemoryStore, invalidate_node_memory
from src.long_term_memory.tools import install_tools
from src.web_backend.node_memory_records import write_jsonl_records


def records(trace: str, user: str, answer: str, age: int = 7200) -> list[dict]:
    date = datetime.fromtimestamp(time.time() - age, timezone.utc).isoformat()
    return [{"id": f"{trace}-{role}", "role": role, "trace_id": trace, "created_at": date,
             "parts": [{"type": "text", "text": text}]} for role, text in (("user", user), ("assistant", answer))]


def write_history(folder: Path, rows: list[dict]):
    folder.mkdir(parents=True, exist_ok=True)
    write_jsonl_records(str(folder / "messages.jsonl"), rows)


def summary_for(sources: list[dict], preference: str = "") -> str:
    return "v1\n\n## User Profile\n\n## User preferences\n" + preference + "\n## General Tips\n\n## What's in Memory\n" + "\n".join(
        f"- memory:{s['id']} — {s['trace_id']}" for s in sources)


class RecordingModel:
    """Protocol fixture only; quality is evaluated separately with a real configured model."""
    def __init__(self):
        self.calls = []
        self.fail_extract = False
        self.during_consolidation = None

    def complete(self, phase, instructions, payload):
        self.calls.append((phase, payload))
        if phase == "extract":
            if self.fail_extract:
                return "```json\n{}\n```"
            return encode({"rollout_summary": "\n".join(r["text"] for r in payload["records"]), "rollout_slug": "fixture"})
        if self.during_consolidation:
            self.during_consolidation()
        return encode({"memory_summary": summary_for(payload["sources"]), "source_ids": [s["id"] for s in payload["sources"]]})


def setup_node(tmp_path):
    folder = tmp_path / "node"
    write_history(folder, records("old", "Use prefix opaque-739 for cache.", "Verified using tool output."))
    store = MemoryStore(folder, "graph", "node")
    model = RecordingModel()
    return folder, store, model, MemoryPipeline(store, model, MemorySettings())


def test_extract_publish_inject_and_retrieve_after_recent_history_loses_fact(tmp_path):
    folder, store, model, pipeline = setup_node(tmp_path)
    old = json.loads((folder / "messages.jsonl").read_text().splitlines()[0])
    # Evidence remains in an archive while the active window contains only unrelated work.
    archive = folder / "archive" / old["created_at"][:10]
    archive.mkdir(parents=True)
    (folder / "messages.jsonl").replace(archive / "messages.jsonl")
    recent = sum((records(f"recent{i}", f"format text {i}", "done", age=2) for i in range(4)), [])
    write_history(folder, recent)
    result = pipeline.run()
    assert result["extracted"] == 1 and result["published"]
    reader = MemoryReader(store)
    assert "opaque-739" not in encode(recent[-6:])
    hit = reader.search("opaque-739")["matches"][0]
    assert f"memory:{hit['source_id']}" in reader.summary()
    evidence = reader.read(hit["source_id"], evidence=True)
    assert "old-user" in evidence["content"] and "opaque-739" in evidence["content"]
    assert pipeline.run()["extracted"] == 0
    assert len(model.calls) == 2  # no duplicate extraction/consolidation


def test_node_isolation_and_host_bound_tools(tmp_path):
    _, store, _, pipeline = setup_node(tmp_path)
    pipeline.run()
    foreign = load_sources(store.node_dir)[0].id
    other = MemoryStore(tmp_path / "other", "graph", "other")
    reader = MemoryReader(other)
    assert reader.search("opaque-739")["matches"] == []
    with pytest.raises(ValueError, match="this node"):
        reader.read(foreign)
    with pytest.raises(ValueError, match="owner"):
        MemoryStore(store.node_dir, "graph", "other")
    functions = {}
    class Registry:
        def register_external_tool(self, declaration, function):
            assert "node_id" not in declaration["function"]["parameters"]["properties"]
            functions[function.__name__] = function
    class Agent:
        tools = Registry()
    install_tools(Agent(), reader)
    with pytest.raises(TypeError):
        functions["read_node_memory"](foreign, node_id="node")


def test_source_correction_invalidates_old_summary_and_reextracts(tmp_path):
    folder, store, model, pipeline = setup_node(tmp_path)
    pipeline.run()
    write_history(folder, records("old", "Correction: use revised-812.", "Confirmed."))
    assert MemoryReader(store).summary() == ""
    assert MemoryReader(store).search("opaque-739")["matches"] == []
    pipeline.run()
    assert MemoryReader(store).search("revised-812")["matches"]
    assert len([c for c in model.calls if c[0] == "extract"]) == 2


def test_deleted_sources_disappear_and_reset_clears_user_edits(tmp_path):
    folder, store, _, pipeline = setup_node(tmp_path)
    pipeline.run()
    source_id = load_sources(folder)[0].id
    write_history(folder, [])
    assert MemoryReader(store).summary() == ""
    pipeline.run()
    with pytest.raises(ValueError):
        MemoryReader(store).read(source_id)
    store.add_note("Forget the old deployment region.")
    invalidate_node_memory(str(folder), reset=True)
    assert store.notes() == [] and store.publication() is None


def test_history_change_during_model_request_cannot_publish(tmp_path):
    folder, store, model, pipeline = setup_node(tmp_path)
    model.during_consolidation = lambda: write_history(folder, [])
    with pytest.raises(Exception, match="changed during consolidation"):
        pipeline.run()
    assert store.publication() is None
    with store.connect() as db:
        assert db.execute("SELECT status FROM runs").fetchone()[0] == "failed"


def test_reset_during_request_fences_publication_even_when_history_unchanged(tmp_path):
    _, store, model, pipeline = setup_node(tmp_path)
    model.during_consolidation = lambda: store.invalidate(reset=True)
    with pytest.raises(Exception, match="changed during consolidation"):
        pipeline.run()
    assert store.publication() is None


def test_bad_model_output_is_a_visible_retryable_failure(tmp_path):
    _, store, model, pipeline = setup_node(tmp_path)
    model.fail_extract = True
    report = pipeline.run()
    assert report["status"] == "partial_failure" and report["failed"] == 1
    with store.connect() as db:
        source = db.execute("SELECT status,error,retry_at FROM sources").fetchone()
        assert source["status"] == "failed" and source["error"] and source["retry_at"] > time.time()
    pipeline.run()
    assert len([c for c in model.calls if c[0] == "extract"]) == 1


def test_empty_extraction_does_not_get_retried(tmp_path):
    _, store, _, _ = setup_node(tmp_path)
    class Empty:
        def complete(self, phase, instructions, payload):
            assert phase == "extract"
            return '{"rollout_summary":"","rollout_slug":""}'
    pipeline = MemoryPipeline(store, Empty(), MemorySettings())
    assert pipeline.run()["no_output"] == 1
    assert pipeline.run()["no_output"] == 0


def test_live_and_incomplete_runs_are_excluded(tmp_path):
    folder, store, model, pipeline = setup_node(tmp_path)
    write_history(folder, records("active", "active", "pending") + records("incomplete", "unfinished", "ignored")[:1])
    report = pipeline.run(active_trace="active")
    assert report["extracted"] == 0 and model.calls == []


def test_lease_prevents_duplicate_workers_and_recovers_after_expiry(tmp_path):
    _, store, _, pipeline = setup_node(tmp_path)
    first = PipelineLease(store, 30)
    assert first.claim()
    assert pipeline.run()["status"] == "busy_or_backoff"
    first.finish()
    with store.connect() as db:
        db.execute("UPDATE jobs SET lease_until=?,status='running'", (time.time() - 1,))
    assert pipeline.run()["extracted"] == 1


def test_unknown_model_pointer_is_rejected():
    with pytest.raises(MemoryContractError):
        Consolidation.parse(encode({"memory_summary": summary_for([{"id": "f"*64, "trace_id": "invented"}]),
                                   "source_ids": ["f"*64]}), set())


def test_user_note_invalidates_summary_and_enters_consolidation(tmp_path):
    _, store, model, pipeline = setup_node(tmp_path)
    pipeline.run()
    store.add_note("Correction: do not retain the old prefix.")
    assert store.publication() is None
    pipeline.run()
    assert model.calls[-1][1]["user_edits"][0]["content"].startswith("Correction")


def test_retention_removes_routes_without_reextracting_expired_sources(tmp_path):
    folder, store, model, pipeline = setup_node(tmp_path)
    pipeline.run()
    future = time.time() + 40 * 86400
    pipeline.run(now=future)
    assert "memory:" not in store.publication()["summary"]
    assert len([c for c in model.calls if c[0] == "extract"]) == 1


def test_forgetting_blocks_exact_source_and_survives_changed_history(tmp_path):
    folder, store, _, pipeline = setup_node(tmp_path)
    pipeline.run()
    source_id = load_sources(folder)[0].id
    store.forget_source(source_id)
    assert list((store.root / "generations").iterdir()) == []
    reader = MemoryReader(store)
    assert reader.search("opaque-739")["matches"] == []
    with pytest.raises(ValueError, match="this node"):
        reader.read(source_id)
    write_history(folder, records("old", "same forgotten topic changed", "new answer"))
    assert pipeline.run()["extracted"] == 0
    assert reader.search("forgotten")["matches"] == []


def test_memory_id_and_retention_are_enforced_before_usage_refresh(tmp_path):
    folder, store, _, pipeline = setup_node(tmp_path)
    pipeline.run()
    source_id = load_sources(folder)[0].id
    reader = MemoryReader(store)
    with pytest.raises(ValueError, match="64-character"):
        reader.read("memory:" + source_id)
    with store.connect() as db:
        db.execute("UPDATE sources SET last_used=?", (time.time() - 40 * 86400,))
    with pytest.raises(ValueError, match="this node"):
        reader.read(source_id)
    assert reader.summary() == ""


def test_serialized_history_clear_invalidates_publication_and_notes(tmp_path):
    from src.web_backend.node_memory_store import clear_node_memory
    folder, store, _, pipeline = setup_node(tmp_path)
    pipeline.run()
    store.add_note("a note")
    clear_node_memory(str(folder / "memory.md"), str(folder / "messages.jsonl"))
    assert store.publication() is None and store.notes() == []
    assert MemoryReader(store).search("opaque-739")["matches"] == []


def test_prepare_binds_tools_and_ephemeral_context_and_schedules(tmp_path, monkeypatch):
    from src.long_term_memory import service
    folder, store, _, pipeline = setup_node(tmp_path)
    pipeline.run()
    scheduled = []
    monkeypatch.setattr(service, "configured_settings", lambda: MemorySettings())
    monkeypatch.setattr(service, "schedule_memory", lambda *a, **kw: scheduled.append((a, kw)))
    class Agent:
        def __init__(self):
            self.messages, self.registered = [], {}
            self.tools = self
        def register_external_tool(self, declaration, function):
            self.registered[function.__name__] = function
        def Message(self, role, content, persist):
            self.messages.append((role, content, persist))
    agent = Agent()
    service.prepare_node_memory(agent, node_dir=str(folder), graph_id="graph", node_id="node",
                                provider_id="fixture", role="developer", active_trace="current")
    assert agent.messages[0][0] == "developer" and agent.messages[0][2] is False
    assert "memory:" in agent.messages[0][1]
    assert set(agent.registered) == {"search_node_memory", "read_node_memory", "add_node_memory_note", "forget_node_memory"}
    assert scheduled[0][1]["active_trace"] == "current"


def test_move_keeps_memory_identity_and_rejects_active_pipeline(tmp_path):
    from src.long_term_memory.lifecycle import require_memory_idle, rebind_memory
    folder, store, _, pipeline = setup_node(tmp_path)
    pipeline.run()
    lease = PipelineLease(store, 30)
    assert lease.claim()
    try:
        with pytest.raises(ValueError, match="running"):
            require_memory_idle(str(folder))
    finally:
        lease.finish()
    require_memory_idle(str(folder))
    target = tmp_path / "target"
    folder.replace(target)
    rebind_memory(str(target), "graph", "new-graph", "node", "node")
    moved = MemoryStore(target, "new-graph", "node")
    assert MemoryReader(moved).search("opaque-739")["matches"]
    with pytest.raises(ValueError, match="owner"):
        MemoryStore(target, "graph", "node")


def test_settings_reject_unstructured_values_and_unknown_fields():
    for value in ({"enabled": "true"}, {"max_extractions": 0}, {"unused": 1}, []):
        with pytest.raises(ValueError):
            MemorySettings.from_config({"longTermMemory": value})


def test_credentials_are_redacted_in_derived_state(tmp_path):
    folder, store, _, pipeline = setup_node(tmp_path)
    secret = "sk-proj-abcdefghijklmnop12345"
    write_history(folder, records("secret", "Bearer " + secret, "Do not preserve credentials"))
    store.add_note(secret)
    pipeline.run()
    assert secret not in encode(store.notes())
    with store.connect() as db:
        assert secret not in db.execute("SELECT payload FROM sources").fetchone()[0]


def test_config_migration_retires_only_memory_rules():
    from scripts.migrate_node_memory import migrate
    rules = [{"action": "node.dispatch", "params": {"profile_ids": ["MemoryNoteWriter", "Reviewer"]}},
             {"action": "context.append_file", "params": {"paths": ["Note.md", "AGENTS.md"]}}]
    result = migrate(rules)
    assert result[0]["params"]["profile_ids"] == ["Reviewer"]
    assert result[1]["params"]["paths"] == ["AGENTS.md"]


def test_edit_during_selection_cannot_publish_a_mixed_snapshot(tmp_path, monkeypatch):
    _, store, _, pipeline = setup_node(tmp_path)
    original_notes = store.notes
    def concurrent_edit():
        snapshot = original_notes()
        store.add_note("A newly arrived preference must not be lost")
        return snapshot
    monkeypatch.setattr(store, "notes", concurrent_edit)
    with pytest.raises(Exception, match="changed during consolidation"):
        pipeline.run()
    assert store.publication() is None
    with store.connect() as db:
        assert db.execute("SELECT retry_at FROM jobs").fetchone()[0] == 0


def test_clear_memory_button_endpoint_removes_history_and_long_term_memory():
    from fastapi.testclient import TestClient
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    client = TestClient(backend.create_app())
    response = client.post("/api/nodes/instances", json={
        "node_id": "memory-clear-test", "type_id": "agent_node", "graph_id": "default",
        "ui": {"grid_x": 1, "grid_y": 2},
    })
    assert response.status_code == 200
    folder = Path(_get_graphs_dir()) / "default" / "memory-clear-test"
    write_history(folder, records("active-file", "Remember clear-probe-739", "Confirmed"))
    archived = records("archived-file", "Older clear-probe-812", "Confirmed", age=172800)
    archive = folder / "archive" / archived[0]["created_at"][:10]
    write_history(archive, archived)
    store = MemoryStore(folder, "default", "memory-clear-test")
    store.add_note("Explicit old preference")
    model = RecordingModel()
    pipeline = MemoryPipeline(store, model, MemorySettings())
    assert pipeline.run()["extracted"] == 2
    source_id = MemoryReader(store).search("clear-probe-739")["matches"][0]["source_id"]
    other = MemoryStore(folder.parent / "other-node", "default", "other-node")
    other.add_note("Preserve another node's preference")

    response = client.post("/api/nodes/instances/memory-clear-test/clear-memory?graph_id=default")
    assert response.status_code == 200 and response.json()["ok"]
    assert load_sources(folder) == []
    assert (archive / "messages.jsonl").read_text(encoding="utf-8") == ""
    assert store.notes() == [] and store.publication() is None
    assert list((store.root / "generations").iterdir()) == []
    with pytest.raises(ValueError, match="this node"):
        MemoryReader(store).read(source_id)
    assert other.notes()[0]["content"] == "Preserve another node's preference"
    previous_calls = len(model.calls)
    assert pipeline.run()["extracted"] == 0
    assert len(model.calls) == previous_calls
