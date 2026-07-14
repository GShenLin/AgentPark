import json
import threading
from types import SimpleNamespace

from src.message_protocol import build_text_envelope


class _FakeLiveOutputs:
    def clear(self, *_args, **_kwargs):
        return None

    def publish_event(self, *_args, **_kwargs):
        return None

    def publish_completion_event(self, *_args, **_kwargs):
        return None

    def update(self, *_args, **_kwargs):
        return None


class _FakeCancellations:
    def begin(self, _config_path):
        return threading.Event()

    def end(self, _config_path, _cancel_event):
        return None


class _FakeHost:
    def __init__(self):
        self.events = []
        self.memory_entries = []
        self.core = SimpleNamespace(
            node_live_outputs=_FakeLiveOutputs(),
            node_cancellations=_FakeCancellations(),
        )

    def _parse_pending_node_item(self, _pending_item):
        return build_text_envelope("run failing work", role="user"), "trace-err", "link-1", 0, 0, "test", 0, []

    def _inject_node_config_into_context(self, _context, _cfg):
        return None

    def _log_graph_event(self, _graph_id, event, **payload):
        self.events.append({"event": event, **payload})

    def _append_runtime_log(self, *_args, **_kwargs):
        return None

    def _append_node_tool_call_entry(self, *_args, **_kwargs):
        return None

    def _append_node_memory_entry(self, graph_id, node_id, role, message):
        self.memory_entries.append((graph_id, node_id, role, message))

    def _node_dir(self, graph_id, node_id):
        return f"C:/tmp/{graph_id}/{node_id}"

    def _node_memory_path(self, node_id, graph_id):
        return f"C:/tmp/{graph_id}/{node_id}/memory.md"

    def _node_messages_path(self, node_id, graph_id):
        return f"C:/tmp/{graph_id}/{node_id}/messages.jsonl"

    def _evaluate_node_goal_after_persist(self, **_kwargs):
        return {"active": False, "should_continue": False}

    def _should_skip_propagation(self, _message):
        return False


def test_companion_node_review_enabled_reads_agent_node_switch():
    from src.companion_notice_settings import companion_node_review_enabled
    from src.companion_notice_settings import companion_tool_failure_memory_enabled

    assert companion_node_review_enabled({}) is False
    assert companion_node_review_enabled({"agentNode": {}}) is False
    assert companion_node_review_enabled({"agentNode": {"reviewNodeRunsWithCompanion": True}}) is True
    assert companion_node_review_enabled({"agentNode": {"reviewNodeRunsWithCompanion": False}}) is False
    assert companion_tool_failure_memory_enabled({}) is False
    assert companion_tool_failure_memory_enabled({"agentNode": {}}) is False
    assert companion_tool_failure_memory_enabled({"agentNode": {"reviseToolFailureMemoryWithCompanion": True}}) is True
    assert companion_tool_failure_memory_enabled({"agentNode": {"reviseToolFailureMemoryWithCompanion": False}}) is False


def test_node_review_notice_format_instructs_companion_to_review_without_report():
    from src.companion_inbox import format_companion_notice
    from src.node_run_companion import build_node_run_review_notice

    notice = build_node_run_review_notice(
        graph_id="default",
        node_id="Agent1",
        node_type_id="agent_node",
        trace_id="trace-1",
        from_node="Trigger1",
        input_preview="start work",
        output_preview="done",
        duration_ms=123,
        goal_result={"goal_state": {"status": "complete", "reason": "verified"}},
        node_dir="C:/tmp/default/Agent1",
        memory_path="C:/tmp/default/Agent1/memory.md",
        messages_path="C:/tmp/default/Agent1/messages.jsonl",
        runtime_events_path="C:/tmp/default/Agent1/runtime_events.jsonl",
    )

    text = format_companion_notice(notice)

    assert "A node run was persisted" in text
    assert "Do not write a separate review report unless the user explicitly asks for one." in text
    assert "Node: default/Agent1" in text
    assert "Triggered by node: default/Trigger1" in text
    assert "Goal status after run: complete" in text
    assert "Memory file: C:/tmp/default/Agent1/memory.md" in text
    assert "Operational memory file to edit when warranted:" in text
    assert "operational_memory.json" in text
    assert "If the persisted run reveals a reusable behavior correction" in text
    assert "Write report to:" not in text
    assert "tool calls, tool results, and final answer" in text


def test_companion_graph_node_run_does_not_deliver_review_notice(monkeypatch):
    import src.node_run_companion as node_run_companion

    delivered = []
    monkeypatch.setattr(node_run_companion, "deliver_companion_notice", lambda notice: delivered.append(notice) or True)

    result = node_run_companion.notify_companion_about_node_run(
        graph_id="Companion",
        node_id="Helper",
        node_type_id="agent_node",
        trace_id="trace-companion-helper",
    )

    assert result is False
    assert delivered == []


def test_non_agent_node_run_does_not_deliver_review_notice(monkeypatch):
    import src.node_run_companion as node_run_companion

    delivered = []
    monkeypatch.setattr(node_run_companion, "deliver_companion_notice", lambda notice: delivered.append(notice) or True)

    result = node_run_companion.notify_companion_about_node_run(
        graph_id="default",
        node_id="Trigger1",
        node_type_id="basic_trigger_node",
        trace_id="trace-trigger",
    )

    assert result is False
    assert delivered == []


def test_graph_node_success_does_not_use_legacy_companion_inbox(monkeypatch, tmp_path):
    import src.companion_notice_settings as companion_notice_settings
    import src.web_backend.graph_node_execution as graph_node_execution
    from src.web_backend import runtime_paths
    from src.web_backend.graph_node_execution import GraphNodeExecution

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "Companion" / "Companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "Companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(
        companion_notice_settings.ConfigLoader,
        "get_config",
        lambda _self: {"agentNode": {"reviewNodeRunsWithCompanion": True}},
    )

    config_path = graphs_dir / "default" / "Agent1" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "node_id": "Agent1",
                "graph_id": "default",
                "type_id": "agent_node",
                "state": "working",
                "pending": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_run_node_logic(_nodes_dir, _type_id, _pending_message, _context):
        return {"message": build_text_envelope("completed answer", role="assistant"), "routes": []}

    monkeypatch.setattr(graph_node_execution, "_run_node_logic_with_routes", fake_run_node_logic)
    host = _FakeHost()

    GraphNodeExecution(host)._run_single_node_iteration(
        safe_graph_id="default",
        entry="Agent1",
        cfg={},
        config_path=str(config_path),
        pending_item={"from": "Trigger1"},
        outgoing={},
        nodes_dir=str(tmp_path),
        wake_event=threading.Event(),
    )

    assert not (companion_config.parent / "inbox.jsonl").exists()
    assert not any(item["event"] == "node_run_companion_review_notice" for item in host.events)


def test_graph_node_persists_response_metadata_as_assistant_sidecar(monkeypatch, tmp_path):
    import src.web_backend.graph_node_execution as graph_node_execution
    from src.web_backend.graph_node_execution import GraphNodeExecution

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "node_id": "Agent1",
                "graph_id": "default",
                "type_id": "agent_node",
                "state": "working",
                "pending": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assistant = {
        "id": "assistant-1",
        "role": "assistant",
        "parts": [{"type": "text", "text": "completed answer"}],
    }
    metadata = {
        "id": "metadata-1",
        "role": "metadata",
        "parts": [
            {
                "type": "structured",
                "data": {
                    "kind": "response_metadata",
                    "scope": "final_assistant",
                    "target": {"type": "message", "message_id": "assistant-1"},
                    "response_metadata": {
                        "protocol": "responses",
                        "response": {"id": "resp-1", "status": "completed"},
                        "output_items": [{"type": "message", "id": "output-1"}],
                    },
                },
            }
        ],
    }

    monkeypatch.setattr(
        graph_node_execution,
        "_run_node_logic_with_routes",
        lambda *_args, **_kwargs: {"message": assistant, "routes": [], "memory_sidecars": [metadata]},
    )
    host = _FakeHost()

    GraphNodeExecution(host)._run_single_node_iteration(
        safe_graph_id="default",
        entry="Agent1",
        cfg={},
        config_path=str(config_path),
        pending_item={"from": "Trigger1"},
        outgoing={},
        nodes_dir=str(tmp_path),
        wake_event=threading.Event(),
    )

    persisted = [(role, message) for _graph, _node, role, message in host.memory_entries]
    assert [role for role, _message in persisted] == ["assistant", "metadata"]
    assert persisted[0][1]["id"] == "assistant-1"
    assert persisted[0][1]["parts"] == [{"type": "text", "text": "completed answer"}]
    metadata_data = persisted[1][1]["parts"][0]["data"]
    assert metadata_data["scope"] == "final_assistant"
    assert metadata_data["target"] == {"type": "message", "message_id": "assistant-1"}
    assert metadata_data["response_metadata"]["response"]["id"] == "resp-1"
    assert metadata_data["response_metadata"]["output_items"] == [{"type": "message", "id": "output-1"}]


def test_graph_node_success_skips_review_notice_for_non_agent_node(monkeypatch, tmp_path):
    import src.companion_notice_settings as companion_notice_settings
    import src.web_backend.graph_node_execution as graph_node_execution
    from src.web_backend import runtime_paths
    from src.web_backend.graph_node_execution import GraphNodeExecution

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "Companion" / "Companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "Companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(
        companion_notice_settings.ConfigLoader,
        "get_config",
        lambda _self: {"agentNode": {"reviewNodeRunsWithCompanion": True}},
    )

    config_path = graphs_dir / "default" / "Trigger1" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "node_id": "Trigger1",
                "graph_id": "default",
                "type_id": "basic_trigger_node",
                "state": "working",
                "pending": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_run_node_logic(_nodes_dir, _type_id, _pending_message, _context):
        return {"message": build_text_envelope("trigger completed", role="assistant"), "routes": []}

    monkeypatch.setattr(graph_node_execution, "_run_node_logic_with_routes", fake_run_node_logic)
    host = _FakeHost()

    GraphNodeExecution(host)._run_single_node_iteration(
        safe_graph_id="default",
        entry="Trigger1",
        cfg={},
        config_path=str(config_path),
        pending_item={"from": ""},
        outgoing={},
        nodes_dir=str(tmp_path),
        wake_event=threading.Event(),
    )

    assert not (companion_config.parent / "inbox.jsonl").exists()
    assert not any(item["event"] == "node_run_companion_review_notice" for item in host.events)
