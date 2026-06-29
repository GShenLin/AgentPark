import json
import threading
from types import SimpleNamespace

from src.message_protocol import build_text_envelope


class _FakeLiveOutputs:
    def clear(self, *_args, **_kwargs):
        return None

    def publish_event(self, *_args, **_kwargs):
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

    def _append_node_tool_call_entry(self, *_args, **_kwargs):
        return None

    def _append_node_memory_entry(self, *_args, **_kwargs):
        return None

    def _evaluate_node_goal_after_persist(self, **_kwargs):
        return {"active": False, "should_continue": False}

    def _should_skip_propagation(self, _message):
        return False


def test_node_error_notice_format_instructs_companion_to_fix_and_restore():
    from src.companion_inbox import format_companion_notice
    from src.node_error_companion import build_node_error_notice

    notice = build_node_error_notice(
        graph_id="default",
        node_id="Agent1",
        node_type_id="agent_node",
        error="RuntimeError: boom",
        error_message="Error: RuntimeError: boom",
        trigger={"from_node": "Trigger1", "trace_id": "trace-1", "input": "start work"},
        traceback_text="Traceback line",
    )

    text = format_companion_notice(notice)

    assert "This is an error notice." in text
    assert "fix the code, then restore the affected node so it can run again" in text
    assert "Errored node: default/Agent1" in text
    assert "Triggered by node: default/Trigger1" in text
    assert "Error: RuntimeError: boom" in text
    assert "Original input: start work" in text


def test_graph_node_error_delivers_companion_notice(monkeypatch, tmp_path):
    import src.web_backend.graph_node_execution as graph_node_execution
    from src.web_backend import runtime_paths
    from src.web_backend.graph_node_execution import GraphNodeExecution

    graphs_dir = tmp_path / "memories"
    companion_config = graphs_dir / "companion" / "config.json"
    companion_config.parent.mkdir(parents=True)
    companion_config.write_text(
        json.dumps({"graph_id": "companion", "type_id": "agent_node"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

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
        raise RuntimeError("boom")

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

    inbox_text = (companion_config.parent / "inbox.jsonl").read_text(encoding="utf-8")
    notice = json.loads(inbox_text.strip())
    assert notice["type"] == "node_error_notice"
    assert notice["source"]["graph_id"] == "default"
    assert notice["source"]["node_id"] == "Agent1"
    assert notice["source"]["node_type_id"] == "agent_node"
    assert notice["issue"]["error"] == "RuntimeError: boom"
    assert notice["issue"]["trigger"]["from_node"] == "Trigger1"
    assert notice["recovery"]["original_input"] == "run failing work"
    event = next(item for item in host.events if item["event"] == "node_error_companion_notice")
    assert event["delivered"] is True
