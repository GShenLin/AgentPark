import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src import user_interaction_store as store
from src.user_interaction_schema import InteractionValidationError, normalize_interaction_schema
from src.web_backend.user_interaction_api import UserInteractionApiDomain


def request(fields=None, agent=None):
    return store.create_interaction_request(schema=normalize_interaction_schema(title="Review", fields=fields), timeout_sec=30, agent=agent)


@pytest.mark.parametrize("field,value", [
    ({"id": "f", "type": "text", "label": "Text", "required": True}, " "),
    ({"id": "f", "type": "checkbox", "label": "Confirm", "required": True}, False),
    ({"id": "f", "type": "checkbox", "label": "Confirm"}, "true"),
    ({"id": "f", "type": "select", "label": "Select", "options": [{"value": "a"}]}, "invented"),
    ({"id": "f", "type": "multiselect", "label": "Select", "options": [{"value": "a"}]}, ["a", "a"]),
    ({"id": "f", "type": "select", "label": "Select", "options": [{"value": "a", "disabled": True}]}, "a"),
])
def test_invalid_answers_never_complete_a_request(field, value):
    pending = request([field])
    with pytest.raises(InteractionValidationError):
        store.submit_interaction_response(pending["id"], {"values": {"f": value}})
    assert store.read_interaction_request(pending["id"])["status"] == "pending"


def test_file_answer_is_separate_and_required():
    pending = request([{"id": "attachment", "type": "file", "label": "File", "required": True}])
    with pytest.raises(InteractionValidationError):
        store.submit_interaction_response(pending["id"], {"files": {"attachment": []}})
    answer = {"files": {"attachment": [{"path": "/uploads/a.txt", "name": "a.txt"}]}}
    assert store.submit_interaction_response(pending["id"], answer)["status"] == "submitted"


def test_concurrent_clients_have_exactly_one_winner():
    pending = request()
    barrier = threading.Barrier(2)

    def submit(value):
        barrier.wait()
        try:
            return store.submit_interaction_response(pending["id"], {"values": {"message": value}})["status"]
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, ["first", "second"])) == ["conflict", "submitted"]
    accepted = store.read_interaction_request(pending["id"])
    assert store.close_pending_interaction(pending["id"], "Stopped")["response"] == accepted["response"]


def test_late_answer_expires_before_accepting_even_without_a_list_or_waiter(monkeypatch):
    pending = request()
    monkeypatch.setattr(store.time, "time", lambda: pending["expires_at"] + 1)
    with pytest.raises(ValueError, match="expired"):
        store.submit_interaction_response(pending["id"], {"values": {"message": "too late"}})
    assert store.read_interaction_request(pending["id"])["status"] == "expired"


def test_stopping_agent_closes_the_visible_request(monkeypatch):
    from src.runtime_cancellation import CancellationRequested
    pending = request()
    def stop(_source):
        raise CancellationRequested()
    monkeypatch.setattr(store, "raise_if_cancel_requested", stop)
    result = store.wait_for_interaction_response(pending["id"], timeout_sec=30)
    assert result["status"] == "cancelled"
    assert store.list_interaction_requests() == []


def test_restart_interrupts_pending_requests_without_overwriting_answers():
    pending, completed = request(), request()
    store.submit_interaction_response(completed["id"], {"values": {"message": "accepted"}})
    store.interrupt_pending_interactions()
    assert store.read_interaction_request(pending["id"])["status"] == "cancelled"
    assert store.read_interaction_request(completed["id"])["status"] == "submitted"


def test_schema_rejects_duplicate_field_ids_and_invalid_defaults():
    field = {"id": "x", "type": "text", "label": "X"}
    with pytest.raises(InteractionValidationError, match="unique"):
        normalize_interaction_schema(title="x", fields=[field, field])
    with pytest.raises(InteractionValidationError):
        normalize_interaction_schema(title="x", fields=[{**field, "default": False}])


def test_http_validation_conflicts_and_visibility_have_distinct_contracts():
    pending = request()
    events = []
    core = SimpleNamespace(default_graph_id="default", graph_runtime=SimpleNamespace(
        _log_graph_event=lambda *args, **kwargs: events.append((args, kwargs))))
    api = UserInteractionApiDomain(core)
    with pytest.raises(HTTPException) as invalid:
        api.submit_user_interaction(pending["id"], {"response": {"values": {"message": ""}}})
    assert invalid.value.status_code == 422
    assert not events
    api.submit_user_interaction(pending["id"], {"response": {"values": {"message": "OK"}}})
    with pytest.raises(HTTPException) as conflict:
        api.submit_user_interaction(pending["id"], {"response": {"values": {"message": "again"}}})
    assert conflict.value.status_code == 409
    assert api.get_user_interaction(pending["id"])["request"]["status"] == "submitted"
    def deny(*_args):
        raise HTTPException(404, "hidden")
    core.graph_api = SimpleNamespace(require_graph_visible=deny)
    with pytest.raises(HTTPException) as hidden:
        api.get_user_interaction(pending["id"], request=object())
    assert hidden.value.status_code == 404


def test_missing_or_broken_delivery_channel_does_not_leave_orphan_requests():
    import json
    from functions.user_interaction_tools import ask_user
    assert json.loads(ask_user("Input"))["status"] == "error"
    assert store.list_interaction_requests() == []
    def fail(_event):
        raise RuntimeError("event delivery failed")
    result = json.loads(ask_user("Input", agent=SimpleNamespace(config={}, tool_event_callback=fail)))
    assert result["status"] == "error"
    assert store.list_interaction_requests() == []
    assert store.list_interaction_requests("all")[0]["status"] == "cancelled"
