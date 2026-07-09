import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from src.web_backend.core import BackendCore
from src.web_backend.graph_node_execution import GraphNodeExecution
from src.web_backend.node_config_service import node_config_service
from src.web_backend.node_memory_store import append_node_memory_entry, load_recent_node_memory_records
from src.operational_memory import load_operational_memory
from src.message_protocol import build_text_envelope


def _patch_workspace(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths
    from src.web_backend import profile_storage

    monkeypatch.setattr(runtime_paths, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(profile_storage, "get_workspace_root", lambda: str(tmp_path))


def _write_graph_node(tmp_path, graph_id, node_id, *, state="idle", type_id="agent_node", extra=None):
    graph_dir = tmp_path / "memories" / graph_id
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "config.json").write_text(
        json.dumps({"id": graph_id, "name": graph_id, "output_routes": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    node_dir = graph_dir / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    payload = {"node_id": node_id, "graph_id": graph_id, "type_id": type_id, "name": node_id, "state": state}
    if isinstance(extra, dict):
        payload.update(extra)
    node_config_service.create_or_replace(str(node_dir / "config.json"), payload)
    return node_dir


def _write_agent_profile(tmp_path, profile_id="companion_tool_failure"):
    profile_dir = tmp_path / "agent"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / f"{profile_id}.json").write_text(
        json.dumps(
            {
                "id": profile_id,
                "name": "Companion Tool Failure",
                "node_type_id": "agent_node",
                "fields": {"provider_id": "unit", "instruction": "review runtime event"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _event_config(source_graph="Test", source_node="Agent", *, action="context.produce", target="builtin.environment_context"):
    event = "OnInput" if action != "node.dispatch" else "ToolFailure"
    return {
        "schema_version": 1,
        "enabled": True,
        "rules": {
            event: {
                source_graph: {
                    source_node: {
                        "enabled": True,
                        "action": action,
                        "target": target,
                    }
                }
            }
        },
        "context_producers": {
            "builtin.environment_context": {"kind": "builtin", "enabled": True, "priority": "normal"}
        },
        "notice_writers": {
            "builtin.runtime_event_notice": {"kind": "builtin", "enabled": True}
        },
        "receiver_groups": {},
        "context_policy": {
            "default_ttl": "next_turn",
            "max_fragment_chars": 8000,
            "max_artifacts_per_event": 20,
            "dedupe_window_ms": 0,
        },
    }


def _set_rule_params(config, event, graph_id, node_id, params):
    config["rules"][event][graph_id][node_id]["params"] = params


def _legacy_event_config(source_graph="Test", source_node="Agent", *, action="context.produce", target="builtin.environment_context"):
    event = "OnInput" if action != "node.dispatch" else "ToolFailure"
    config = _event_config(source_graph, source_node, action=action, target=target)
    config["rules"] = [
        {
            "source": {"graph_id": source_graph, "node_id": source_node},
            "event": event,
            "enabled": True,
            "action": action,
            "target": target,
        }
    ]
    return config


class _RuntimeEventCapture:
    def __init__(self):
        self.events = []

    def emit(self, **kwargs):
        self.events.append(kwargs)
        return {"matched": 0, "executed": 0, "artifacts": 0, "errors": []}

    def consume_context_fragments(self, **_kwargs):
        return []


class _NoopLiveOutputs:
    def update(self, *_args, **_kwargs):
        return None

    def clear(self, *_args, **_kwargs):
        return None

    def publish_event(self, *_args, **_kwargs):
        return None

    def publish_completion_event(self, *_args, **_kwargs):
        return None

    def update_thinking(self, *_args, **_kwargs):
        return None


class _NoopCancellations:
    def begin(self, _config_path):
        return threading.Event()

    def end(self, _config_path, _cancel_event):
        return None


class _GraphExecutionHost:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.runtime_events = _RuntimeEventCapture()
        self.core = SimpleNamespace(
            runtime_events=self.runtime_events,
            node_live_outputs=_NoopLiveOutputs(),
            node_cancellations=_NoopCancellations(),
        )

    def _parse_pending_node_item(self, _pending_item):
        return build_text_envelope("start", role="user"), "trace-run", None, 0, 0, "test", 0, []

    def _inject_node_config_into_context(self, _context, _cfg):
        return None

    def _log_graph_event(self, *_args, **_kwargs):
        return None

    def _append_runtime_log(self, *_args, **_kwargs):
        return None

    def _append_node_tool_call_entry(self, *_args, **_kwargs):
        return None

    def _append_node_memory_entry(self, *_args, **_kwargs):
        return None

    def _evaluate_node_goal_after_persist(self, **_kwargs):
        return {"active": False, "should_continue": False}

    def _should_skip_propagation(self, _message):
        return True

    def _node_dir(self, graph_id, node_id):
        path = self.tmp_path / "memories" / graph_id / node_id
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _node_messages_path(self, node_id, graph_id):
        return str(self.tmp_path / "memories" / graph_id / node_id / "messages.jsonl")

    def _node_config_path(self, node_id, graph_id):
        return str(self.tmp_path / "memories" / graph_id / node_id / "config.json")


def test_runtime_event_no_match_is_fast_in_memory_return(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    core = BackendCore()
    core.runtime_events.registry.apply(_event_config())

    result = core.runtime_events.emit(
        event="ToolFailure",
        graph_id="Test",
        node_id="Agent",
        node_type_id="agent_node",
        trace_id="trace-1",
        payload={"error": "boom"},
    )

    assert result["matched"] == 0
    assert result["executed"] == 0


def test_legacy_list_rules_are_saved_as_event_keyed_rules(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    core = BackendCore()

    result = core.runtime_events.registry.apply(_legacy_event_config())
    saved = json.loads((tmp_path / "config" / "events.json").read_text(encoding="utf-8"))

    assert result["compiled"]["enabled_rules"] == 1
    assert isinstance(saved["rules"], dict)
    assert saved["rules"]["OnInput"]["Test"]["Agent"]["target"] == "builtin.environment_context"


def test_runtime_event_context_produce_injects_from_memory_store(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    core = BackendCore()
    core.runtime_events.registry.apply(_event_config())

    result = core.runtime_events.emit(
        event="OnInput",
        graph_id="Test",
        node_id="Agent",
        node_type_id="agent_node",
        trace_id="trace-1",
        payload={"working_path": str(tmp_path)},
    )
    fragments = core.runtime_events.consume_context_fragments(graph_id="Test", node_id="Agent")

    assert result["matched"] == 1
    assert result["artifacts"] == 1
    assert any("Runtime environment context" in item for item in fragments)
    assert core.runtime_events.consume_context_fragments(graph_id="Test", node_id="Agent") == []


def test_graph_execution_emits_work_persisted_after_success(tmp_path, monkeypatch):
    import src.web_backend.graph_node_execution as graph_node_execution

    node_dir = _write_graph_node(tmp_path, "Test", "Agent")
    config_path = node_dir / "config.json"

    def fake_run_node_logic(_nodes_dir, _type_id, _pending_message, _context):
        return {"message": build_text_envelope("done", role="assistant"), "routes": []}

    monkeypatch.setattr(graph_node_execution, "_run_node_logic_with_routes", fake_run_node_logic)
    host = _GraphExecutionHost(tmp_path)

    GraphNodeExecution(host)._run_single_node_iteration(
        safe_graph_id="Test",
        entry="Agent",
        cfg={},
        config_path=str(config_path),
        pending_item={},
        outgoing={},
        nodes_dir=str(tmp_path),
        wake_event=threading.Event(),
    )

    assert [item["event"] for item in host.runtime_events.events][-1] == "WorkPersisted"
    assert host.runtime_events.events[-1]["payload"]["final_message_preview"] == "done"


def test_graph_execution_emits_work_failed_after_error_persistence(tmp_path, monkeypatch):
    import src.web_backend.graph_node_execution as graph_node_execution

    node_dir = _write_graph_node(tmp_path, "Test", "Agent")
    config_path = node_dir / "config.json"

    def fake_run_node_logic(_nodes_dir, _type_id, _pending_message, _context):
        raise RuntimeError("boom")

    monkeypatch.setattr(graph_node_execution, "_run_node_logic_with_routes", fake_run_node_logic)
    host = _GraphExecutionHost(tmp_path)

    GraphNodeExecution(host)._run_single_node_iteration(
        safe_graph_id="Test",
        entry="Agent",
        cfg={},
        config_path=str(config_path),
        pending_item={},
        outgoing={},
        nodes_dir=str(tmp_path),
        wake_event=threading.Event(),
    )

    assert [item["event"] for item in host.runtime_events.events][-1] == "WorkFailed"
    assert "RuntimeError: boom" in host.runtime_events.events[-1]["payload"]["error"]


def test_persistent_context_result_uses_operational_memory_patch(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    core = BackendCore()
    config = _event_config(action="context.produce", target="builtin.environment_context")
    _set_rule_params(config, "OnInput", "Test", "Agent", {"ttl": "persistent"})
    core.runtime_events.registry.apply(config)

    result = core.runtime_events.emit(
        event="OnInput",
        graph_id="Test",
        node_id="Agent",
        node_type_id="agent_node",
        trace_id="trace-memory",
        payload={},
    )
    memory = load_operational_memory(str(tmp_path / "memories" / "Test" / "Agent" / "operational_memory.json"))

    assert result["matched"] == 1
    assert result["artifacts"] == 1
    assert memory["memories"]
    assert core.runtime_events.consume_context_fragments(graph_id="Test", node_id="Agent") == []


def test_node_dispatch_uses_idle_explicit_receiver_without_creating_temp_node(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    _write_graph_node(tmp_path, "Companion", "Companion", state="idle")
    _write_agent_profile(tmp_path)
    core = BackendCore()
    monkeypatch.setattr(core.graph_runtime, "_ensure_graph_runner", lambda graph_id: None)
    monkeypatch.setattr(core.graph_runtime, "_wake_graph_runner", lambda graph_id: None)
    group_config = _event_config(action="node.dispatch", target="companion_review")
    group_config["receiver_groups"] = {
        "companion_review": {
            "enabled": True,
            "graph_id": "Companion",
            "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
            "event_profiles": {"ToolFailure": "companion_tool_failure"},
            "receivers": [{"graph_id": "Companion", "node_id": "Companion"}],
        }
    }
    core.runtime_events.registry.apply(group_config)

    core.runtime_events.emit(
        event="ToolFailure",
        graph_id="Test",
        node_id="Agent",
        node_type_id="agent_node",
        trace_id="trace-dispatch",
        payload={"tool_name": "read_file", "status": "error", "error": "failed"},
    )
    companion_config_path = tmp_path / "memories" / "Companion" / "Companion" / "config.json"
    deadline = time.time() + 2
    pending = []
    while time.time() < deadline:
        cfg = node_config_service.read_optional_object(str(companion_config_path))
        pending = cfg.get("pending") if isinstance(cfg.get("pending"), list) else []
        if pending:
            break
        time.sleep(0.02)

    assert pending
    assert pending[0]["source"] == "runtime_event_dispatch"
    temp_nodes = [
        item.name
        for item in (tmp_path / "memories" / "Companion").iterdir()
        if item.is_dir() and item.name != "Companion"
    ]
    assert temp_nodes == []


def test_node_dispatch_fallback_creates_temporary_profile_receiver(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    _write_graph_node(tmp_path, "Companion", "Companion", state="working")
    _write_agent_profile(tmp_path)
    core = BackendCore()
    monkeypatch.setattr(core.graph_runtime, "_ensure_graph_runner", lambda graph_id: None)
    monkeypatch.setattr(core.graph_runtime, "_wake_graph_runner", lambda graph_id: None)
    group_config = _event_config(action="node.dispatch", target="companion_review")
    group_config["receiver_groups"] = {
        "companion_review": {
            "enabled": True,
            "graph_id": "Companion",
            "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
            "event_profiles": {"ToolFailure": "companion_tool_failure"},
            "receivers": [{"graph_id": "Companion", "node_id": "Companion"}],
        }
    }
    core.runtime_events.registry.apply(group_config)

    core.runtime_events.emit(
        event="ToolFailure",
        graph_id="Test",
        node_id="Agent",
        node_type_id="agent_node",
        trace_id="trace-dispatch",
        payload={"tool_name": "read_file", "status": "error", "error": "failed"},
    )

    companion_dir = tmp_path / "memories" / "Companion"
    deadline = time.time() + 2
    temp_config = {}
    temp_config_path = None
    while time.time() < deadline:
        for item in companion_dir.iterdir():
            config_path = item / "config.json"
            if item.is_dir() and item.name != "Companion" and config_path.exists():
                temp_config_path = config_path
                temp_config = node_config_service.read_optional_object(str(config_path))
                break
        pending = temp_config.get("pending") if isinstance(temp_config.get("pending"), list) else []
        if temp_config and pending:
            break
        time.sleep(0.02)
    if temp_config_path is not None:
        temp_config = node_config_service.read_optional_object(str(temp_config_path))

    meta = temp_config.get("runtime_event_receiver")
    assert meta["temporary"] is True
    assert meta["merge_target"] == {"graph_id": "Companion", "node_id": "Companion"}
    assert temp_config["pending"][0]["source"] == "runtime_event_dispatch"


def test_receiver_group_requires_profile_for_dispatched_event(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    _write_graph_node(tmp_path, "Companion", "Companion")
    _write_agent_profile(tmp_path)
    core = BackendCore()
    group_config = _event_config(action="node.dispatch", target="companion_review")
    group_config["receiver_groups"] = {
        "companion_review": {
            "enabled": True,
            "graph_id": "Companion",
            "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
            "event_profiles": {"RuntimeNotice": "companion_tool_failure"},
            "receivers": [{"graph_id": "Companion", "node_id": "Companion"}],
        }
    }

    try:
        core.runtime_events.registry.apply(group_config)
    except Exception as exc:
        errors = getattr(exc, "errors", [])
    else:
        errors = []

    assert any("has no profile for event ToolFailure" in item["message"] for item in errors)


def test_temporary_receiver_cleanup_merges_once_and_deletes_node(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    companion_dir = _write_graph_node(tmp_path, "Companion", "Companion")
    temp_dir = _write_graph_node(
        tmp_path,
        "Companion",
        "TempReceiver",
        extra={
            "runtime_event_receiver": {
                "temporary": True,
                "receiver_group": "companion_review",
                "profile_id": "companion_tool_failure",
                "created_for_event": "ToolFailure",
                "creation_trace_id": "trace-merge",
                "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
            }
        },
    )
    append_node_memory_entry(
        str(temp_dir / "memory.md"),
        str(temp_dir / "messages.jsonl"),
        "user",
        {"id": "temp-input", "role": "user", "parts": [{"type": "text", "text": "Runtime event dispatch.\nEvent: ToolFailure\nSource: Test/Agent\nerror: failed"}]},
    )
    append_node_memory_entry(
        str(temp_dir / "memory.md"),
        str(temp_dir / "messages.jsonl"),
        "assistant",
        {"id": "temp-output", "role": "assistant", "parts": [{"type": "text", "text": "fix optional memory"}]},
    )
    core = BackendCore()

    result = core.runtime_events.cleanup.cleanup_now(graph_id="Companion", node_id="TempReceiver")
    records = load_recent_node_memory_records(str(companion_dir / "memory.md"), str(companion_dir / "messages.jsonl"), limit=10)

    assert result["ok"] is True
    assert not temp_dir.exists()
    assert any(item["id"] == "runtime-event-merge:Companion:TempReceiver:trace-merge" for item in records)
    assert any(
        item["role"] == "user" and "Runtime event dispatch." in json.dumps(item, ensure_ascii=False)
        for item in records
    )
    assert any(
        item["role"] == "assistant" and "fix optional memory" in json.dumps(item, ensure_ascii=False)
        for item in records
    )
    assert any("fix optional memory" in json.dumps(item, ensure_ascii=False) for item in records)


def test_failed_temporary_receiver_cleanup_keeps_node_for_inspection(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    temp_dir = _write_graph_node(
        tmp_path,
        "Companion",
        "TempReceiver",
        extra={
            "runtime_event_receiver": {
                "temporary": True,
                "receiver_group": "companion_review",
                "profile_id": "companion_tool_failure",
                "created_for_event": "ToolFailure",
                "creation_trace_id": "trace-merge",
                "merge_target": {"graph_id": "Companion", "node_id": "MissingCompanion"},
            }
        },
    )
    core = BackendCore()

    result = core.runtime_events.cleanup.cleanup_now(graph_id="Companion", node_id="TempReceiver")
    cfg = node_config_service.read_optional_object(str(temp_dir / "config.json"))

    assert result["ok"] is False
    assert temp_dir.exists()
    assert cfg["runtime_event_receiver"]["cleanup_status"] == "merge_error"


def test_temporary_receiver_cleanup_preserves_merge_state_when_destroy_fails(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    companion_dir = _write_graph_node(tmp_path, "Companion", "Companion")
    temp_dir = _write_graph_node(
        tmp_path,
        "Companion",
        "TempDestroyFail",
        extra={
            "runtime_event_receiver": {
                "temporary": True,
                "receiver_group": "companion_review",
                "profile_id": "companion_tool_failure",
                "created_for_event": "ToolFailure",
                "creation_trace_id": "trace-destroy-fail",
                "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
            }
        },
    )
    append_node_memory_entry(
        str(temp_dir / "memory.md"),
        str(temp_dir / "messages.jsonl"),
        "assistant",
        {"id": "temp-destroy-output", "role": "assistant", "parts": [{"type": "text", "text": "destroy failed"}]},
    )
    core = BackendCore()

    def fail_delete(*_args, **_kwargs):
        raise RuntimeError("delete locked")

    deletion_service = next(
        target for target in core.node_ops._iter_service_targets()
        if type(target).__name__ == "NodeInstanceDeletion"
    )
    object.__setattr__(deletion_service, "delete_node_instance", fail_delete)
    result = core.runtime_events.cleanup.cleanup_now(graph_id="Companion", node_id="TempDestroyFail")
    state = json.loads((temp_dir / ".runtime_event_merge.json").read_text(encoding="utf-8"))
    records = load_recent_node_memory_records(str(companion_dir / "memory.md"), str(companion_dir / "messages.jsonl"), limit=10)

    assert result["ok"] is False
    assert temp_dir.exists()
    assert state["status"] == "merge_error"
    assert state["records_merged"] is True
    assert state["operational_memory_merged"] is True
    assert any("destroy failed" in json.dumps(item, ensure_ascii=False) for item in records)


def test_concurrent_temporary_receiver_cleanup_keeps_all_companion_records(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    companion_dir = _write_graph_node(tmp_path, "Companion", "Companion")
    temp_ids = ["TempOne", "TempTwo", "TempThree"]
    for index, temp_id in enumerate(temp_ids):
        temp_dir = _write_graph_node(
            tmp_path,
            "Companion",
            temp_id,
            extra={
                "runtime_event_receiver": {
                    "temporary": True,
                    "receiver_group": "companion_review",
                    "profile_id": "companion_tool_failure",
                    "created_for_event": "ToolFailure",
                    "creation_trace_id": f"trace-{index}",
                    "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
                }
            },
        )
        append_node_memory_entry(
            str(temp_dir / "memory.md"),
            str(temp_dir / "messages.jsonl"),
            "assistant",
            {
                "id": f"temp-output-{index}",
                "role": "assistant",
                "parts": [{"type": "text", "text": f"temporary correction {index}"}],
            },
        )
    core = BackendCore()

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(
                lambda node_id: core.runtime_events.cleanup.cleanup_now(graph_id="Companion", node_id=node_id),
                temp_ids,
            )
        )
    records = load_recent_node_memory_records(str(companion_dir / "memory.md"), str(companion_dir / "messages.jsonl"), limit=20)
    text = json.dumps(records, ensure_ascii=False)

    assert all(result["ok"] for result in results)
    for index, temp_id in enumerate(temp_ids):
        assert not (tmp_path / "memories" / "Companion" / temp_id).exists()
        assert f"runtime-event-merge:Companion:{temp_id}:trace-{index}" in {item["id"] for item in records}
        assert f"temporary correction {index}" in text


def test_companion_append_and_read_during_temporary_receiver_merge(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    companion_dir = _write_graph_node(tmp_path, "Companion", "Companion")
    temp_ids = ["TempReadOne", "TempReadTwo"]
    for index, temp_id in enumerate(temp_ids):
        temp_dir = _write_graph_node(
            tmp_path,
            "Companion",
            temp_id,
            extra={
                "runtime_event_receiver": {
                    "temporary": True,
                    "receiver_group": "companion_review",
                    "profile_id": "companion_tool_failure",
                    "created_for_event": "ToolFailure",
                    "creation_trace_id": f"trace-read-{index}",
                    "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
                }
            },
        )
        append_node_memory_entry(
            str(temp_dir / "memory.md"),
            str(temp_dir / "messages.jsonl"),
            "assistant",
            {
                "id": f"temp-read-output-{index}",
                "role": "assistant",
                "parts": [{"type": "text", "text": f"read merge correction {index}"}],
            },
        )
    core = BackendCore()

    def merge(node_id):
        return core.runtime_events.cleanup.cleanup_now(graph_id="Companion", node_id=node_id)

    def normal_append_and_read():
        append_node_memory_entry(
            str(companion_dir / "memory.md"),
            str(companion_dir / "messages.jsonl"),
            "user",
            {"id": "normal-during-merge", "role": "user", "parts": [{"type": "text", "text": "normal write"}]},
        )
        return load_recent_node_memory_records(str(companion_dir / "memory.md"), str(companion_dir / "messages.jsonl"), limit=20)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(merge, node_id) for node_id in temp_ids]
        futures.append(executor.submit(normal_append_and_read))
        outputs = [future.result() for future in futures]
    records = load_recent_node_memory_records(str(companion_dir / "memory.md"), str(companion_dir / "messages.jsonl"), limit=20)
    ids = {item["id"] for item in records}

    assert all(output["ok"] for output in outputs[:2])
    assert "normal-during-merge" in ids
    assert any("read merge correction 0" in json.dumps(item, ensure_ascii=False) for item in records)
    assert any("read merge correction 1" in json.dumps(item, ensure_ascii=False) for item in records)


def test_companion_startup_recovery_clears_runtime_event_inbox(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Companion", "Companion")
    config_path = tmp_path / "memories" / "Companion" / "Companion" / "config.json"
    node_config_service.update(
        str(config_path),
        lambda payload: payload.update(
            {
                "pending": [
                    {"source": "runtime_event_dispatch", "payload": "drop"},
                    {"source": "user", "payload": "keep"},
                ],
                "pending_count": 2,
            }
        ),
        effective="immediate",
    )
    core = BackendCore()

    result = core.runtime_events.startup_recovery.run()
    cfg = node_config_service.read_optional_object(str(config_path))

    assert result["companion_inbox_cleared"] == 1
    assert [item["source"] for item in cfg["pending"]] == ["user"]


def test_companion_startup_recovery_ensures_canonical_graph_and_node(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    core = BackendCore()

    result = core.runtime_events.startup_recovery.run()
    graph_config = tmp_path / "memories" / "Companion" / "config.json"
    node_config = tmp_path / "memories" / "Companion" / "Companion" / "config.json"

    assert result["canonical"]["graph_created"] is True
    assert result["canonical"]["node_created"] is True
    assert graph_config.exists()
    assert node_config.exists()
    assert node_config_service.read_optional_object(str(node_config))["type_id"] == "agent_node"


def test_companion_startup_recovery_merges_and_deletes_leftover_receiver(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    companion_dir = _write_graph_node(tmp_path, "Companion", "Companion")
    temp_dir = _write_graph_node(
        tmp_path,
        "Companion",
        "StartupTemp",
        extra={
            "runtime_event_receiver": {
                "temporary": True,
                "receiver_group": "companion_review",
                "profile_id": "companion_tool_failure",
                "created_for_event": "ToolFailure",
                "creation_trace_id": "trace-startup",
                "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
            }
        },
    )
    append_node_memory_entry(
        str(temp_dir / "memory.md"),
        str(temp_dir / "messages.jsonl"),
        "assistant",
        {"id": "startup-temp-output", "role": "assistant", "parts": [{"type": "text", "text": "startup fix"}]},
    )
    core = BackendCore()

    result = core.runtime_events.startup_recovery.run()
    records = load_recent_node_memory_records(str(companion_dir / "memory.md"), str(companion_dir / "messages.jsonl"), limit=10)

    assert result["temporary_receivers_found"] == 1
    assert result["temporary_receivers_cleaned"] == 1
    assert not temp_dir.exists()
    assert any("startup fix" in json.dumps(item, ensure_ascii=False) for item in records)


def test_events_apply_api_validates_writes_and_keeps_diagnostics(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")

    import src.web_backend as backend
    from fastapi.testclient import TestClient

    client = TestClient(backend.create_app())
    config = _event_config()
    applied = client.post("/api/events/apply", json={"config": config})
    invalid = client.post(
        "/api/events/apply",
        json={
            "config": {
                **config,
                "rules": {
                    "OnInput": {
                        "Test": {
                            "Agent": {
                                "enabled": True,
                                "action": "context.produce",
                                "target": "builtin.missing",
                            }
                        }
                    }
                },
            }
        },
    )
    diagnostics = client.get("/api/events/diagnostics")
    saved = json.loads((tmp_path / "config" / "events.json").read_text(encoding="utf-8"))

    assert applied.status_code == 200
    assert applied.json()["ok"] is True
    assert invalid.status_code == 200
    assert invalid.json()["ok"] is False
    assert diagnostics.status_code == 200
    assert diagnostics.json()["compiled"]["enabled_rules"] == 1
    assert saved["rules"]["OnInput"]["Test"]["Agent"]["target"] == "builtin.environment_context"


def test_events_apply_without_config_reloads_existing_file(tmp_path, monkeypatch):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "Test", "Agent")
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    existing = _event_config()
    (config_dir / "events.json").write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    import src.web_backend as backend
    from fastapi.testclient import TestClient

    client = TestClient(backend.create_app())
    response = client.post("/api/events/apply", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["compiled"]["enabled_rules"] == 1
