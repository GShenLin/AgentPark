from __future__ import annotations

from src.user_interaction_store import (
    create_interaction_request,
    list_interaction_requests,
    normalize_interaction_schema,
    submit_interaction_response,
    wait_for_interaction_response,
)
from src.web_backend.core import BackendCore


def test_interaction_store_submits_response(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_memories_root", lambda: str(tmp_path / "memories"))

    schema = normalize_interaction_schema(
        title="需要确认",
        fields=[
            {"id": "note", "type": "textarea", "label": "说明", "required": True},
            {
                "id": "choices",
                "type": "multiselect",
                "label": "选项",
                "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
            },
        ],
    )
    request = create_interaction_request(schema=schema, timeout_sec=30)

    pending = list_interaction_requests()
    assert [item["id"] for item in pending] == [request["id"]]

    submit_interaction_response(request["id"], {"values": {"note": "hello", "choices": ["a"]}})
    completed = wait_for_interaction_response(request["id"], timeout_sec=1)

    assert completed["status"] == "submitted"
    assert completed["response"]["values"]["note"] == "hello"
    assert list_interaction_requests() == []


def test_interaction_schema_rejects_invalid_select_options(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_memories_root", lambda: str(tmp_path / "memories"))

    try:
        normalize_interaction_schema(
            title="bad",
            fields=[{"id": "choice", "type": "select", "label": "Choice"}],
        )
    except ValueError as exc:
        assert "options is required" in str(exc)
    else:
        raise AssertionError("expected invalid schema to raise")


def test_interaction_schema_accepts_custom_html(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_memories_root", lambda: str(tmp_path / "memories"))

    schema = normalize_interaction_schema(
        title="custom",
        fields=[
            {
                "id": "designer",
                "type": "custom_html",
                "label": "设计器",
                "html": "<button>提交</button>",
                "css": "button { color: red; }",
                "js": "window.AGENTPARK_INTERACTION.submit({ ok: true })",
                "height": 500,
                "initial_data": {"mode": "demo"},
            }
        ],
    )

    field = schema["fields"][0]
    assert field["type"] == "custom_html"
    assert field["height"] == 500
    assert field["initial_data"]["mode"] == "demo"


def test_interaction_schema_rejects_custom_html_without_html(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_memories_root", lambda: str(tmp_path / "memories"))

    try:
        normalize_interaction_schema(
            title="bad custom",
            fields=[{"id": "designer", "type": "custom_html", "label": "设计器"}],
        )
    except ValueError as exc:
        assert "html is required" in str(exc)
    else:
        raise AssertionError("expected invalid custom_html schema to raise")


def test_ask_user_emits_created_and_submitted_runtime_notices(tmp_path, monkeypatch):
    import json

    from functions.user_interaction_tools import ask_user

    monkeypatch.setattr("src.user_interaction_store.get_memories_root", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(
        "functions.user_interaction_tools.wait_for_interaction_response",
        lambda request_id, **_kwargs: {
            "id": request_id,
            "status": "submitted",
            "response": {"values": {"confirmed": True}},
        },
    )
    events = []

    class FakeAgent:
        config = {"graph_id": "graph-a", "node_instance_id": "node-a", "name": "Node A"}
        tool_event_callback = staticmethod(events.append)

    ask_user("确认", agent=FakeAgent())

    assert [event["stage"] for event in events] == [
        "user_interaction_created",
        "user_interaction_submitted",
    ]
    assert all(event["source"] == "user_interaction" for event in events)
    created_payload = json.loads(events[0]["message"])
    assert created_payload == {
        "description": "",
        "graph_id": "graph-a",
        "node_id": "node-a",
        "node_name": "Node A",
        "request_id": created_payload["request_id"],
        "status": "pending",
        "title": "确认",
    }


def test_submit_interaction_publishes_graph_event(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_memories_root", lambda: str(tmp_path / "memories"))
    request = create_interaction_request(
        schema=normalize_interaction_schema(title="确认"),
        timeout_sec=30,
        agent=type(
            "FakeAgent",
            (),
            {"config": {"graph_id": "graph-a", "node_instance_id": "node-a", "name": "Node A"}},
        )(),
    )
    core = BackendCore()

    result = core.user_interaction_api.submit_user_interaction(
        request["id"],
        {"status": "submitted", "response": {"values": {"confirmed": True}}},
    )

    assert result["request"]["status"] == "submitted"
    event = core.graph_events.get("graph-a")
    assert event["event"] == "user_interaction_submitted"
    assert event["request_id"] == request["id"]
    assert event["node_instance_id"] == "node-a"
