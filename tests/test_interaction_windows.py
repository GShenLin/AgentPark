import json
from types import SimpleNamespace

from src.user_interaction_schema import normalize_interaction_schema
from src.user_interaction_store import create_interaction_request, read_interaction_request, close_pending_interaction
from src.web_backend.graph_event_stream import GraphEventStreamStore
from src.web_backend.interaction_windows import InteractionWindows
from tests.test_node_window_alerts import wait_for


def pending():
    return create_interaction_request(schema=normalize_interaction_schema(title="Input"), timeout_sec=30,
        agent=SimpleNamespace(config={"graph_id": "g", "node_id": "n"}))


def created(request):
    return {"event": "runtime_notice", "source": "user_interaction", "stage": "user_interaction_created",
            "message": json.dumps({"request_id": request["id"]})}


def test_backend_opens_request_once_without_any_browser_connection():
    events, calls = GraphEventStreamStore(), []
    service = InteractionWindows(events, lambda *args: calls.append(args))
    request = pending()
    service.start(8788)
    try:
        events.publish("g", created(request))
        events.publish("g", created(request))
        wait_for(lambda: read_interaction_request(request["id"]).get("desktop", {}).get("status") == "opened")
        assert calls == [(request["id"], 8788)]
        assert events.get("g")["event"] == "user_interaction_delivery"
    finally:
        service.close()


def test_closed_and_snapshot_requests_never_launch():
    events, calls = GraphEventStreamStore(), []
    service = InteractionWindows(events, lambda *args: calls.append(args))
    request = pending()
    close_pending_interaction(request["id"], "Stopped")
    service.start(8788)
    try:
        events.publish("g", created(request))
        events.publish("g", {**created(pending()), "stream_snapshot": True})
    finally:
        service.close()
    assert not calls


def test_failed_widget_is_visible_in_request_and_later_requests_still_deliver():
    events = GraphEventStreamStore()
    def fail(*_args):
        raise RuntimeError("Electron missing")
    service = InteractionWindows(events, fail)
    first, second = pending(), pending()
    service.start(8788)
    try:
        events.publish("g", created(first))
        wait_for(lambda: read_interaction_request(first["id"]).get("desktop", {}).get("status") == "failed")
        assert read_interaction_request(first["id"])["desktop"]["error"] == "Electron missing"
        service.launch = lambda *_: {"ok": True}
        events.publish("g", created(second))
        wait_for(lambda: read_interaction_request(second["id"]).get("desktop", {}).get("status") == "opened")
    finally:
        service.close()
