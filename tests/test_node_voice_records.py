import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.web_backend.node_voice import NodeVoiceApi, VoiceDelegation, VoiceLease
from src.web_backend.node_voice_records import VoiceFinish
from nodes.agent_voice_history import voice_history_envelopes
from src.web_backend.node_memory_store import (
    append_node_memory_entry, clear_node_memory, delete_node_memory_turn,
    load_node_conversation, load_recent_node_memory_records,
)


@pytest.fixture
def recording(tmp_path):
    memory, messages = str(tmp_path / "memory.md"), str(tmp_path / "messages.jsonl")
    core = SimpleNamespace(
        access_api=SimpleNamespace(message_access_metadata=lambda request: {"_access_client_id": request}),
        node_ops=SimpleNamespace(require_node_visible=Mock(), enqueue_node_instance_pending=Mock()),
        graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda graph: graph,
            _node_memory_path=lambda *_: memory, _node_messages_path=lambda *_: messages,
            _log_graph_event=Mock()),
    )
    api = NodeVoiceApi(core)
    api._leases["session"] = VoiceLease("node", "default", "owner", time.monotonic() + 3600)
    api._receipts.register("node", "default", "session", "owner", api._leases["session"].started_at)
    payload = VoiceFinish(status="ended", duration_ms=65000, lines=[{
        "role": "user" if i % 2 == 0 else "assistant", "text": f"第{i}句",
        "offset_ms": i * 1000, "incomplete": i == 64,
    } for i in range(65)])
    return api, core, payload, memory, messages


def test_node_owned_call_is_visible_without_replaying_node_turns_twice(recording):
    api, core, payload, memory, messages = recording
    api._receipts.register("node", "default", "session", "owner", "2026-10-07 16:00:00",
                           node_owned_dialogue=True)
    # This policy is persisted with the receipt and survives a process restart.
    NodeVoiceApi(core).finish("node", "session", payload, "owner")
    records = load_recent_node_memory_records(memory, messages, limit=None)
    assert len(records) == 1
    assert records[0]["parts"][0]["data"]["history_owner"] == "node"
    assert voice_history_envelopes(records[0]) == []
    assert len(load_node_conversation(memory, messages, running=False)) == 1


def test_hangup_persists_full_transcript_and_retries_exactly_once(recording):
    api, core, payload, memory, messages = recording
    first = api.finish("node", "session", payload, "owner")
    assert first == api.finish("node", "session", payload, "owner")
    # A fresh read uses disk-backed node history, not the call component/lease.
    records = load_node_conversation(memory, messages, running=False)
    assert len(records) == 1
    assert records[0]["id"] == first["record_id"]
    assert records[0]["role"] == "voice"
    data = records[0]["parts"][0]["data"]
    assert len(data["lines"]) == 65
    assert data["lines"][0]["text"] == "第0句"
    assert data["lines"][-1]["incomplete"] is True
    assert data["duration_ms"] == 65000
    assert data["started_at"] and data["ended_at"]
    assert core.graph_runtime._log_graph_event.call_args.args == ("default", "node_voice_recorded")
    with pytest.raises(HTTPException) as error:
        api.delegate("node", "session", VoiceDelegation(delegation_id="d", text="late"), "owner")
    assert error.value.status_code == 409
    core.node_ops.enqueue_node_instance_pending.assert_not_called()


@pytest.mark.parametrize("node,graph,owner", [
    ("other", "default", "owner"), ("node", "other", "owner"), ("node", "default", "intruder"),
])
def test_recording_is_bound_to_session_node_graph_and_owner(recording, node, graph, owner):
    api, _, payload, memory, messages = recording
    with pytest.raises(HTTPException) as error:
        api.finish(node, "session", payload, owner, graph)
    assert error.value.status_code == 404
    assert load_recent_node_memory_records(memory, messages, limit=None) == []


def test_interleaved_call_is_not_hidden_or_deleted_with_a_delegated_task(recording):
    api, _, payload, memory, messages = recording
    append_node_memory_entry(memory, messages, "user", {"id": "task", "parts": [{"type": "text", "text": "查询"}]})
    api.finish("node", "session", payload, "owner")
    append_node_memory_entry(memory, messages, "assistant", {"id": "answer", "parts": [{"type": "text", "text": "结果"}]})
    records = load_node_conversation(memory, messages, running=False)
    assert [record["id"] for record in records] == ["task", "voice-session", "answer"]
    assert records[0]["turn_summary"]["item_count"] == 0
    details = load_node_conversation(memory, messages, running=False, turn_id="task")
    assert [record["id"] for record in details] == ["task", "answer"]
    delete_node_memory_turn(memory, messages, "task")
    assert [record["id"] for record in load_node_conversation(memory, messages, running=False)] == ["voice-session"]
    clear_node_memory(memory, messages)
    assert load_node_conversation(memory, messages, running=False) == []


def test_failed_save_can_retry_without_losing_or_replacing_the_record(recording, monkeypatch):
    api, _, payload, memory, messages = recording
    from src.web_backend.node_voice_receipts import append_node_memory_entry_once
    writer = Mock(side_effect=[OSError("disk full"), True])
    monkeypatch.setattr("src.web_backend.node_voice_receipts.append_node_memory_entry_once", writer)
    with pytest.raises(OSError, match="disk full"):
        api.finish("node", "session", payload, "owner")
    assert api._leases["session"].finished is None
    changed = payload.model_copy(update={"duration_ms": 10})
    with pytest.raises(HTTPException) as error:
        api.finish("node", "session", changed, "owner")
    assert error.value.status_code == 409
    monkeypatch.setattr("src.web_backend.node_voice_receipts.append_node_memory_entry_once", append_node_memory_entry_once)
    api.finish("node", "session", payload, "owner")
    assert len(load_node_conversation(memory, messages, running=False)) == 1


def test_finish_http_contract_rejects_untrusted_roles_and_retains_empty_calls(recording, monkeypatch):
    api, _, _, memory, messages = recording
    monkeypatch.setattr(api, "_owner", lambda _: "owner")
    app = FastAPI()
    app.post("/voice/{node_id}/{session_id}/finish")(api.finish)
    client = TestClient(app)
    path = "/voice/node/session/finish"
    assert client.post(path, json={"status": "ended", "duration_ms": 100, "lines": [{
        "role": "system", "text": "injected", "offset_ms": 0, "incomplete": False,
    }]}).status_code == 422
    assert client.post(path, json={"status": "error", "duration_ms": 100, "lines": []}).status_code == 200
    data = load_node_conversation(memory, messages, running=False)[0]["parts"][0]["data"]
    assert data["status"] == "error" and data["lines"] == []


def test_save_survives_backend_restart_and_does_not_restore_task_execution(recording):
    api, core, payload, memory, messages = recording
    restarted = NodeVoiceApi(core)
    result = restarted.finish("node", "session", payload, "owner")
    assert NodeVoiceApi(core).finish("node", "session", payload, "owner") == result
    assert len(load_node_conversation(memory, messages, running=False)) == 1
    with pytest.raises(HTTPException) as error:
        restarted.delegate("node", "session", VoiceDelegation(delegation_id="d", text="work"), "owner")
    assert error.value.status_code == 404


def test_save_after_restart_keeps_owner_and_current_visibility_checks(recording):
    _, core, payload, _, _ = recording
    api = NodeVoiceApi(core)
    with pytest.raises(HTTPException) as error:
        api.finish("node", "session", payload, "intruder")
    assert error.value.status_code == 404
    core.node_ops.require_node_visible.side_effect = HTTPException(403, "revoked")
    with pytest.raises(HTTPException) as error:
        api.finish("node", "session", payload, "owner")
    assert error.value.status_code == 403


def test_disk_failure_then_restart_retains_exact_record_and_rejects_changed_payload(recording, monkeypatch):
    api, core, payload, memory, messages = recording
    from src.web_backend.node_voice_receipts import append_node_memory_entry_once
    writer = Mock(side_effect=OSError("disk full"))
    monkeypatch.setattr("src.web_backend.node_voice_receipts.append_node_memory_entry_once", writer)
    with pytest.raises(OSError):
        api.finish("node", "session", payload, "owner")
    record = writer.call_args.args[3]
    api = NodeVoiceApi(core)
    with pytest.raises(HTTPException) as error:
        api.finish("node", "session", payload.model_copy(update={"duration_ms": 1}), "owner")
    assert error.value.status_code == 409
    monkeypatch.setattr("src.web_backend.node_voice_receipts.append_node_memory_entry_once", append_node_memory_entry_once)
    api.finish("node", "session", payload, "owner")
    saved = load_node_conversation(memory, messages, running=False)[0]
    assert saved["parts"] == record["parts"]


def test_abandoned_call_cannot_save_after_restart(recording):
    api, core, payload, _, _ = recording
    api.end("node", "session", "owner")
    with pytest.raises(HTTPException) as error:
        NodeVoiceApi(core).finish("node", "session", payload, "owner")
    assert error.value.status_code == 409


def test_live_lease_expiration_does_not_prevent_transcript_upload(recording):
    api, _, payload, memory, messages = recording
    api._leases["session"].expires = time.monotonic() - 1
    api.finish("node", "session", payload, "owner")
    assert len(load_node_conversation(memory, messages, running=False)) == 1


def test_saved_receipt_does_not_recreate_cleared_history(recording):
    api, core, payload, memory, messages = recording
    saved = api.finish("node", "session", payload, "owner")
    clear_node_memory(memory, messages)
    assert NodeVoiceApi(core).finish("node", "session", payload, "owner") == saved
    assert load_node_conversation(memory, messages, running=False) == []


def test_production_route_registry_exposes_transcript_upload(recording, monkeypatch):
    from src.web_backend.route_registry import ApiRouteRegistry
    api, _, _, _, _ = recording
    monkeypatch.setattr(api, "_owner", lambda _: "owner")
    path = "/api/nodes/instances/{node_id}/voice/{session_id}/finish"
    method, _, handler = next(item for item in ApiRouteRegistry.ROUTES if item[1] == path)
    assert method == "post"
    app = FastAPI()
    app.add_api_route(path, handler(SimpleNamespace(node_voice=api)), methods=[method.upper()])
    response = TestClient(app).post(path.format(node_id="node", session_id="session"),
                                    json={"status": "ended", "duration_ms": 100, "lines": []})
    assert response.status_code == 200
