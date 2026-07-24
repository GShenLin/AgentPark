import json
from pathlib import Path


def test_tool_stats_store_groups_counts_by_provider_id(monkeypatch, tmp_path):
    from src.tool import tool_stats_store

    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))

    recorder = tool_stats_store.ToolCallStatsRecorder(provider_id="openai", graph_id="g1", node_id="n1")
    recorder.handle(
        {
            "type": "tool_call_start",
            "name": "read_file",
            "call_id": "call-ok",
            "arguments": {"path": "a.txt"},
            "arguments_json": '{"path":"a.txt"}',
            "raw_call": {"id": "call-ok"},
        }
    )
    recorder.handle(
        {
            "type": "tool_call_end",
            "name": "read_file",
            "call_id": "call-ok",
            "status": "completed",
            "duration_ms": 12,
            "result": "done",
            "result_preview": "done",
        }
    )
    recorder.handle(
        {
            "type": "tool_call_start",
            "name": "execute_console_command",
            "call_id": "call-fail",
            "arguments": {"command": "bad"},
            "raw_call": {"id": "call-fail"},
        }
    )
    recorder.handle(
        {
            "type": "tool_call_end",
            "name": "execute_console_command",
            "call_id": "call-fail",
            "status": "timeout",
            "error": "too slow",
            "result": {"status": "timeout", "error": "too slow"},
            "result_preview": '{"status":"timeout"}',
        }
    )

    records = [
        json.loads(line)
        for line in Path(tool_stats_store.get_tool_calls_log_path()).read_text(encoding="utf-8").splitlines()
    ]
    assert [item["success"] for item in records] == [True, False]
    assert records[0]["provider_id"] == "openai"
    assert records[0]["tool_call_arguments"] == {"path": "a.txt"}
    assert records[0]["tool_call_raw"] == {"id": "call-ok"}
    assert records[1]["result"] == {"status": "timeout", "error": "too slow"}

    summary = json.loads(Path(tool_stats_store.get_tool_stats_summary_path()).read_text(encoding="utf-8"))
    provider = summary["providers"]["openai"]
    assert provider["total"] == 2
    assert provider["success"] == 1
    assert provider["failure"] == 1
    assert provider["tools"]["read_file"]["success"] == 1
    assert provider["tools"]["execute_console_command"]["failure"] == 1

    recent = tool_stats_store.load_recent_tool_call_stats(limit=1)
    assert len(recent) == 1
    assert recent[0]["call_id"] == "call-fail"
    analysis_records = tool_stats_store.load_tool_call_stats(limit=2)
    assert [item["call_id"] for item in analysis_records] == ["call-fail", "call-ok"]
    assert [item["call_id"] for item in tool_stats_store.load_all_tool_call_stats()] == ["call-fail", "call-ok"]
    rebuilt = tool_stats_store.build_tool_stats_summary(tool_stats_store.load_all_tool_call_stats())
    assert rebuilt["providers"]["openai"]["total"] == 2


def test_tool_stats_scope_filters_graph_and_time(monkeypatch):
    from datetime import datetime

    from src.web_backend import tool_stats_scope

    monkeypatch.setattr(
        tool_stats_scope,
        "scope_cutoff",
        lambda _hours: datetime.fromisoformat("2026-07-21T12:00:00"),
    )
    records = [
        {"graph_id": "test", "recorded_at": "2026-07-21T13:00:00+08:00", "call_id": "matching"},
        {"graph_id": "test", "recorded_at": "2026-07-21T11:00:00+08:00", "call_id": "old"},
        {"graph_id": "default", "recorded_at": "2026-07-21T13:00:00+08:00", "call_id": "other"},
    ]

    scoped = tool_stats_scope.filter_tool_call_records(records, graph_id="test", scope_hours=24)

    assert [record["call_id"] for record in scoped] == ["matching"]
    assert tool_stats_scope.available_tool_graph_ids(records) == ["default", "test"]


def test_clear_tool_stats_removes_summary_and_recent_calls(monkeypatch, tmp_path):
    from src.tool import tool_stats_store

    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))

    recorder = tool_stats_store.ToolCallStatsRecorder(provider_id="demo")
    recorder.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-1"})
    recorder.handle({"type": "tool_call_end", "name": "read_file", "call_id": "call-1", "status": "completed"})

    assert Path(tool_stats_store.get_tool_calls_log_path()).is_file()
    assert Path(tool_stats_store.get_tool_stats_summary_path()).is_file()

    reset_at = tool_stats_store.clear_tool_stats()

    assert not Path(tool_stats_store.get_tool_calls_log_path()).exists()
    assert not Path(tool_stats_store.get_tool_stats_summary_path()).exists()
    assert tool_stats_store.load_tool_stats_summary() == {"providers": {}}
    assert tool_stats_store.load_recent_tool_call_stats() == []
    assert tool_stats_store.load_tool_stats_reset_at() == reset_at
    assert Path(tool_stats_store.get_tool_stats_reset_path()).is_file()


def test_corrupt_summary_is_archived_without_breaking_tool_stats(monkeypatch, tmp_path):
    from src.tool import tool_stats_store

    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))
    stats_dir = Path(tool_stats_store.get_tool_stats_dir())
    stats_dir.mkdir(parents=True)
    summary_path = Path(tool_stats_store.get_tool_stats_summary_path())
    summary_path.write_text('{"providers":{"demo":{"tools":{"read_file":{"last_result_preview":"bad', encoding="utf-8")

    recorder = tool_stats_store.ToolCallStatsRecorder(provider_id="demo")
    recorder.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-1"})
    recorder.handle(
        {
            "type": "tool_call_end",
            "name": "read_file",
            "call_id": "call-1",
            "status": "completed",
            "result_preview": "ok",
        }
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["providers"]["demo"]["total"] == 1
    assert summary["providers"]["demo"]["tools"]["read_file"]["last_result_preview"] == "ok"
    assert list(stats_dir.glob("summary.json.corrupt-*"))

    errors = [
        json.loads(line)
        for line in Path(tool_stats_store.get_tool_stats_error_log_path()).read_text(encoding="utf-8").splitlines()
    ]
    assert any(item["stage"] == "summary_recovery" for item in errors)


def test_recorder_does_not_propagate_stats_storage_failure(monkeypatch, tmp_path):
    from src.tool import tool_stats_store

    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))

    def fail_append(_record):
        raise RuntimeError("stats backend is down")

    monkeypatch.setattr(tool_stats_store, "append_tool_call_stat", fail_append)

    recorder = tool_stats_store.ToolCallStatsRecorder(provider_id="demo")
    recorder.handle({"type": "tool_call_end", "name": "read_file", "call_id": "call-1", "status": "completed"})

    errors = [
        json.loads(line)
        for line in Path(tool_stats_store.get_tool_stats_error_log_path()).read_text(encoding="utf-8").splitlines()
    ]
    assert errors[0]["stage"] == "recorder_handle"
    assert errors[0]["error"] == "stats backend is down"


def test_failure_analysis_finds_cross_tool_patterns():
    from src.tool.tool_failure_analysis import build_tool_failure_analysis

    analysis = build_tool_failure_analysis(
        [
            {
                "tool_name": "read_file",
                "success": False,
                "status": "failed",
                "error": "file not found",
                "tool_call_arguments": {"file_path": "missing.txt"},
            },
            {
                "tool_name": "execute_console_command",
                "success": False,
                "status": "failed",
                "error": "command not found",
                "tool_call_arguments": {"command": "missing-command"},
            },
            {
                "tool_name": "execute_console_command",
                "success": False,
                "status": "timeout",
                "error": "command timed out",
                "tool_call_arguments": {"command": "slow-command"},
            },
        ]
    )

    assert analysis["total_failures"] == 3
    assert analysis["affected_tool_count"] == 2
    assert {item["category"]: item["count"] for item in analysis["categories"]} == {
        "read_failed": 1,
        "command_failed": 1,
        "timeout": 1,
    }
    assert analysis["shared_patterns"][0]["category"] == "status:failed"
    assert analysis["shared_patterns"][0]["tools"] == ["execute_console_command", "read_file"]
    assert analysis["tools"]["execute_console_command"]["categories"] == {
        "command_failed": 1,
        "timeout": 1,
    }


def test_failure_history_returns_every_failure_for_selected_tool():
    from src.tool.tool_failure_analysis import build_tool_failure_history

    records = [
        {"tool_name": "read_file", "success": False, "call_id": "read-2"},
        {"tool_name": "execute_console_command", "success": False, "call_id": "exec-1"},
        {"tool_name": "read_file", "success": True, "call_id": "read-ok"},
        {"tool_name": "read_file", "success": False, "call_id": "read-1"},
    ]

    history = build_tool_failure_history(records, "read_file")

    assert history["tool_name"] == "read_file"
    assert history["analyzed_call_count"] == 4
    assert history["failure_count"] == 2
    assert [call["call_id"] for call in history["calls"]] == ["read-2", "read-1"]
