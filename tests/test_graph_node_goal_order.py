import json
import threading
from types import SimpleNamespace

from src.message_protocol import build_text_envelope
from src.web_backend.graph_node_execution import GraphNodeExecution


class _FakeLiveOutputs:
    def __init__(self, order):
        self.order = order

    def update(self, *_args, **_kwargs):
        self.order.append("live_update")

    def clear(self, *_args, **_kwargs):
        self.order.append("live_clear")

    def publish_event(self, _graph_id, _node_id, event, *_args, **_kwargs):
        self.order.append(f"live:{event}")

    def publish_completion_event(self, _graph_id, _node_id, event, *_args, **_kwargs):
        self.order.append(f"live:{event}")


class _FakeCancellations:
    def begin(self, _config_path):
        return threading.Event()

    def end(self, _config_path, _cancel_event):
        return None


class _FakeHost:
    def __init__(self):
        self.order = []
        self.core = SimpleNamespace(
            node_live_outputs=_FakeLiveOutputs(self.order),
            node_cancellations=_FakeCancellations(),
        )

    def _parse_pending_node_item(self, _pending_item):
        return build_text_envelope("start", role="user"), "trace-1", None, 0, 0, "test", 0, []

    def _inject_node_config_into_context(self, _context, _cfg):
        return None

    def _log_graph_event(self, _graph_id, event, **_payload):
        self.order.append(f"log:{event}")

    def _append_runtime_log(self, *_args, **_kwargs):
        self.order.append("runtime_log")

    def _append_node_tool_call_entry(self, *_args, **_kwargs):
        self.order.append("tool_call_memory")

    def _append_node_memory_entry(self, *_args, **_kwargs):
        self.order.append("assistant_memory")

    def _evaluate_node_goal_after_persist(self, **_kwargs):
        self.order.append("goal_eval")
        return {"active": True, "should_continue": False}

    def _should_skip_propagation(self, _message):
        return False


def test_node_output_is_recorded_before_goal_evaluation(monkeypatch, tmp_path):
    import src.web_backend.graph_node_execution as graph_node_execution

    config_path = tmp_path / "node.json"
    config_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "node_id": "n1",
                "graph_id": "g1",
                "type_id": "agent_node",
                "state": "working",
                "pending": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_run_node_logic(_nodes_dir, _type_id, _pending_message, _context):
        return {"message": build_text_envelope("done", role="assistant"), "routes": []}

    monkeypatch.setattr(graph_node_execution, "_run_node_logic_with_routes", fake_run_node_logic)

    host = _FakeHost()
    GraphNodeExecution(host)._run_single_node_iteration(
        safe_graph_id="g1",
        entry="n1",
        cfg={},
        config_path=str(config_path),
        pending_item={},
        outgoing={},
        nodes_dir=str(tmp_path),
        wake_event=threading.Event(),
    )

    assert "assistant_memory" in host.order
    assert "live:node_output" in host.order
    assert "log:node_output" in host.order
    assert "goal_eval" in host.order
    assert host.order.index("assistant_memory") < host.order.index("live:node_output")
    assert "live_clear" not in host.order
    assert host.order.index("live:node_output") < host.order.index("goal_eval")
    assert host.order.index("log:node_output") < host.order.index("goal_eval")
