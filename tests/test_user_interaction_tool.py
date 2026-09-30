from __future__ import annotations

import json

import pytest

from src.user_interaction_store import (
    create_interaction_request,
    list_interaction_requests,
    normalize_interaction_schema,
    submit_interaction_response,
    wait_for_interaction_response,
)
from src.web_backend.core import BackendCore


def test_user_interaction_skill_exposes_tools_only_while_active(tmp_path):
    import json
    from nodes.agent_skill_activation import bind_deferred_skills
    from nodes.agent_support.capability_setup import resolve_agent_capabilities
    from src.tool.base_tool import BaseTool

    plan = resolve_agent_capabilities(
        lambda key, default: {"tools": ["system_tools"], "skills": ["user-interaction"]}.get(key, default),
        node_id="interaction-skill-test",
    )
    agent = type("Agent", (), {"config": {}, "_agentpark_node_directory": str(tmp_path)})()
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.addTool = agent.tools.addTool
    for name in plan.tool_names:
        agent.addTool(name)
    bind_deferred_skills(agent, plan.selected_skill_definitions, role="developer")
    assert "ask_user" not in agent.tools.function_map
    assert "tips" not in agent.tools.function_map
    result = json.loads(agent.tools.execute_tool("activate_skill", {"skill": "user-interaction"}))
    assert result["status"] == "success"
    assert result["tools_added"] == ["ask_user", "tips"]
    closed = json.loads(agent.tools.execute_tool("deactivate_skill", {"skill": "user-interaction"}))
    assert closed["tools_removed"] == ["ask_user", "tips"]
    assert "ask_user" not in agent.tools.function_map
    assert "tips" not in agent.tools.function_map


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


def test_interaction_schema_rejects_removed_custom_html():
    with pytest.raises(ValueError, match="type must be one of"):
        normalize_interaction_schema(
            title="bad custom",
            fields=[{"id": "designer", "type": "custom_html", "label": "设计器", "html": "<button>提交</button>"}],
        )


def test_ask_user_declaration_has_no_custom_form_fields():
    from functions.user_interaction_tools import ask_user_declaration

    fields = ask_user_declaration["function"]["parameters"]["properties"]["fields"]["items"]["properties"]
    assert fields["type"]["enum"] == ["text", "textarea", "select", "multiselect", "checkbox", "file"]
    assert not {"html", "css", "js", "height", "initial_data"}.intersection(fields)


def test_tips_publishes_complete_notification_without_waiting(tmp_path, monkeypatch):
    from functions.user_interaction_tools import tips
    from src.web_backend.node_runtime_event_sink import NodeRuntimeEventSink

    def unexpected_request(*args, **kwargs):
        pytest.fail("Tips must not create or wait for an interaction request")

    monkeypatch.setattr("functions.user_interaction_tools.create_interaction_request", unexpected_request)
    monkeypatch.setattr("functions.user_interaction_tools.wait_for_interaction_response", unexpected_request)
    events = []
    sink = NodeRuntimeEventSink(
        graph_id="graph-a", node_id="node-a", node_type_id="agent_node",
        config_path=str(tmp_path / "config.json"), trace_id="trace-tips", depth=0,
        stream_last_text="", append_tool_call_entry=lambda *_args: None,
        log_graph_event=lambda graph_id, event, **fields: events.append(
            {"graph_id": graph_id, "event": event, **fields}
        ),
    )
    agent = type("Agent", (), {"tool_event_callback": staticmethod(sink.handle)})()
    message = '任务进展 "成功"\n' * 200
    try:
        result = json.loads(tips(message, title="进度提示", agent=agent))
        second = json.loads(tips("第二条提示", agent=agent))
    finally:
        sink.close()

    assert result["status"] == second["status"] == "sent"
    assert result["tip_id"] != second["tip_id"]
    assert len(events) == 2
    assert events[0]["event"] == "runtime_notice"
    assert events[0]["stage"] == "user_tip"
    assert events[0]["source"] == "user_interaction"
    assert events[0]["graph_id"] == "graph-a"
    assert events[0]["node_instance_id"] == "node-a"
    assert json.loads(events[0]["message"]) == {
        "tip_id": result["tip_id"], "title": "进度提示", "message": message.strip(),
    }
    assert json.loads(events[1]["message"])["title"] == "提示"


@pytest.mark.parametrize("arguments", [{"message": " "}, {"message": None}, {"message": "hello", "title": ""}])
def test_tips_rejects_invalid_input(arguments):
    from functions.user_interaction_tools import tips

    events = []
    agent = type("Agent", (), {"tool_event_callback": staticmethod(events.append)})()
    assert json.loads(tips(**arguments, agent=agent))["status"] == "error"
    assert not events


def test_tips_reports_unavailable_channel_and_delivery_errors():
    from functions.user_interaction_tools import tips

    assert json.loads(tips("hello"))["status"] == "error"

    def fail(_event):
        raise RuntimeError("delivery failed")

    agent = type("Agent", (), {"tool_event_callback": staticmethod(fail)})()
    result = json.loads(tips("hello", agent=agent))
    assert result["status"] == "error"
    assert "delivery failed" in result["error"]


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
