import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_backend import node_memory_conversation as projection
from src.web_backend.node_instance_runtime import NodeInstanceRuntime
from src.web_backend.node_memory_store import load_node_conversation
from src.web_backend.mobile_api import MobileApiDomain
from src.web_backend.state_store import _update_node_config_state


def record(key, role, text="body"):
    return {"id": key, "role": role, "parts": [{"type": "text", "text": text}],
            "created_at": "2026-09-27T00:00:00Z"}


def write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")


@pytest.fixture
def history(tmp_path):
    projection._file_index.cache_clear()
    archive = tmp_path / "archive" / "2026-09-26" / "messages.jsonl"
    active = tmp_path / "messages.jsonl"
    rows = [record("u1", "user"), record("p1", "assistant_progress", "PROCESS"),
            record("m1", "metadata", "DETAIL" * 10000), record("a1", "assistant")]
    write(archive, rows[:3])
    write(active, [rows[3], record("u2", "user"), record("t2", "tool", "TOOL")])
    return tmp_path, active, archive


def read(history, **kwargs):
    root, active, _ = history
    return load_node_conversation(str(root / "memory.md"), str(active), running=kwargs.pop("running", False), **kwargs)


def test_all_turn_bodies_visible_but_process_absent_even_while_running(history):
    messages = read(history, running=True)
    assert [m["id"] for m in messages] == ["u1", "a1", "u2"]
    assert messages[0]["turn_summary"]["item_count"] == 2
    assert messages[0]["turn_summary"]["has_metadata"] is True
    assert messages[0]["turn_summary"]["running"] is False
    assert messages[-1]["turn_summary"]["running"] is True
    assert "DETAIL" not in json.dumps(messages)
    assert "TOOL" not in json.dumps(messages)


def test_details_load_only_requested_turn_across_archive_boundary(history):
    assert [m["id"] for m in read(history, turn_id="u1")] == ["u1", "p1", "m1", "a1"]
    assert [m["id"] for m in read(history, turn_id="u2")] == ["u2", "t2"]
    with pytest.raises(KeyError):
        read(history, turn_id="missing")


def test_warm_projection_does_not_decode_process_payloads(history, monkeypatch):
    expected = read(history)
    def unexpected_parse(*args, **kwargs):
        raise AssertionError("Unchanged history must use the lightweight index")
    monkeypatch.setattr(projection, "parse_record_line", unexpected_parse)
    assert read(history) == expected


def test_append_delete_and_restore_invalidate_index_without_changing_older_revision(history):
    _, active, _ = history
    before = read(history)
    saved = active.read_text(encoding="utf-8")
    with active.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record("a2", "assistant", "finished")) + "\n")
    after = read(history)
    assert after[-1]["id"] == "a2"
    assert before[0]["turn_summary"]["revision"] == after[0]["turn_summary"]["revision"]
    assert before[-1]["turn_summary"]["revision"] != after[-2]["turn_summary"]["revision"]
    active.write_text(saved, encoding="utf-8")
    assert read(history) == before


def test_invalid_history_is_reported(history):
    _, active, _ = history
    active.write_text('{"broken":\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSONL"):
        read(history)


def test_http_projection_and_explicit_turn_contract(history):
    root, active, _ = history
    config = root / "config.json"
    config.write_text(json.dumps({"state": "working"}), encoding="utf-8")
    _update_node_config_state(str(config), "working")
    graph = SimpleNamespace(
        _sanitize_graph_id=lambda value: value,
        _resolve_existing_node_id=lambda graph_id, node_id: node_id,
        _node_config_path=lambda *args: str(config),
        _node_memory_path=lambda *args: str(root / "memory.md"),
        _node_messages_path=lambda *args: str(active),
    )
    core = SimpleNamespace(node_live_outputs=SimpleNamespace(get=lambda *args: {}))
    runtime = NodeInstanceRuntime(SimpleNamespace(core=core, graph_runtime=graph))
    core.node_ops = runtime
    app = FastAPI()
    app.get("/memory/{node_id}")(runtime.get_node_instance_memory)
    client = TestClient(app)
    result = client.get("/memory/Agent?graph_id=default&history_mode=conversation")
    assert result.status_code == 200
    payload = result.json()
    assert payload["history_complete"] is True
    assert payload["text"] == ""
    assert [m["id"] for m in payload["messages"]] == ["u1", "a1", "u2"]
    assert payload["messages"][-1]["turn_summary"]["running"] is True
    details = client.get("/memory/Agent?history_mode=turn_details&turn_id=u1")
    assert [m["id"] for m in details.json()["messages"]] == ["u1", "p1", "m1", "a1"]
    assert client.get("/memory/Agent?history_mode=turn_details").status_code == 400
    assert client.get("/memory/Agent?history_mode=conversation&turn_id=u1").status_code == 400
    assert client.get("/memory/Agent?history_mode=turn_details&turn_id=missing").status_code == 404
    mobile = MobileApiDomain(core)
    assert mobile._mobile_node_conversation_snapshot("default", "Agent")["messages"] == payload["messages"]
    mobile_details = mobile._mobile_node_conversation_snapshot("default", "Agent", "turn_details", "u1")
    assert mobile_details["messages"] == details.json()["messages"]
