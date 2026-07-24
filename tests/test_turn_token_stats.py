import json

from src.web_backend.turn_token_stats import load_turn_token_stats


def _record(trace_id, timestamp, stage, payload, *, provider="demo", graph_id="default"):
    event = {
        "type": "runtime_notice",
        "source": "provider_runtime" if stage.startswith("provider_") else "node_runtime",
        "stage": stage,
        "message": json.dumps(payload),
    }
    if provider:
        event["provider"] = provider
    record = {
        "ts": timestamp,
        "event": "runtime_notice",
        "graph_id": graph_id,
        "node_instance_id": "Agent1",
        "trace_id": trace_id,
        "runtime_event": event,
    }
    if stage == "provider_request_summary":
        record["provider_request_summary"] = payload
    if stage == "provider_request_completed":
        record["provider_request_completion"] = payload
    return record


def test_turn_token_stats_builds_cumulative_chart_through_persistence(tmp_path):
    node_dir = tmp_path / "default" / "Agent1"
    node_dir.mkdir(parents=True)
    records = [
        _record("trace-1", "2026-07-15 10:00:00", "node_run_start", {}, provider=""),
        _record("trace-1", "2026-07-15 10:00:01", "provider_request_summary", {"request_index": 1}),
        _record(
            "trace-1",
            "2026-07-15 10:00:02",
            "provider_request_completed",
            {"request_index": 1, "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
        ),
        _record("trace-1", "2026-07-15 10:00:03", "provider_request_summary", {"request_index": 2}),
        _record(
            "trace-1",
            "2026-07-15 10:00:04",
            "provider_request_completed",
            {"request_index": 2, "usage": {"input_tokens": 150, "output_tokens": 30, "total_tokens": 180}},
        ),
        _record("trace-1", "2026-07-15 10:00:05", "node_run_summary", {}, provider=""),
    ]
    (node_dir / "runtime_events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    result = load_turn_token_stats(str(tmp_path))

    provider = result["providers"]["demo"]
    turn = provider["latest_turn"]
    assert provider["turn_count"] == 1
    assert provider["model_turn_count"] == 2
    assert provider["usage_model_turn_count"] == 2
    assert turn["first_response"]["usage"] == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    assert turn["persisted_totals"] == {"input_tokens": 250, "output_tokens": 50, "total_tokens": 300}
    assert [point["label"] for point in turn["chart_points"]] == ["Sent", "Reply 1", "Reply 2", "Completed"]
    assert turn["chart_points"][0]["cumulative_total_tokens"] == 0
    assert turn["chart_points"][-1]["cumulative_total_tokens"] == 300
    assert turn["chart_points"][0]["request_input_tokens"] is None
    assert turn["chart_points"][1]["request_input_tokens"] == 100
    assert turn["chart_points"][1]["request_output_tokens"] == 20
    assert turn["chart_points"][2]["request_input_tokens"] == 150
    assert turn["chart_points"][2]["request_output_tokens"] == 30
    assert turn["chart_points"][-1]["request_output_tokens"] is None


def test_turn_token_stats_excludes_unpersisted_and_marks_usage_free_turns(tmp_path):
    node_dir = tmp_path / "default" / "Agent1"
    node_dir.mkdir(parents=True)
    records = [
        _record("trace-open", "2026-07-15 10:00:01", "provider_request_summary", {"request_index": 1}),
        _record(
            "trace-open",
            "2026-07-15 10:00:02",
            "provider_request_completed",
            {"request_index": 1, "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}},
        ),
        _record("trace-no-usage", "2026-07-15 11:00:01", "provider_request_summary", {"request_index": 1}),
        _record("trace-no-usage", "2026-07-15 11:00:01.500000", "provider_request_completed", {"request_index": 1}),
        _record("trace-no-usage", "2026-07-15 11:00:02", "node_run_summary", {}, provider=""),
    ]
    (node_dir / "runtime_events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    result = load_turn_token_stats(str(tmp_path))

    provider = result["providers"]["demo"]
    assert provider["turn_count"] == 1
    assert provider["usage_turn_count"] == 0
    assert provider["missing_usage_turn_count"] == 1
    assert provider["model_turn_count"] == 1
    assert provider["usage_model_turn_count"] == 0
    turn = provider["latest_turn"]
    assert turn["trace_id"] == "trace-no-usage"
    assert turn["request_count"] == 1
    assert turn["model_turn_count"] == 1
    assert turn["usage_request_count"] == 0
    assert turn["usage_status"] == "missing"
    assert turn["first_response"]["usage"] == {}
    assert [point["label"] for point in turn["chart_points"]] == ["Sent", "Reply 1", "Completed"]
    assert turn["chart_points"][1]["request_input_tokens"] is None


def test_turn_token_stats_skips_invalid_utf8_record_and_reports_diagnostic(tmp_path):
    node_dir = tmp_path / "default" / "Agent1"
    node_dir.mkdir(parents=True)
    records = [
        _record("trace-1", "2026-07-15 10:00:00", "node_run_start", {}, provider=""),
        _record("trace-1", "2026-07-15 10:00:01", "provider_request_summary", {"request_index": 1}),
        _record(
            "trace-1",
            "2026-07-15 10:00:02",
            "provider_request_completed",
            {"request_index": 1, "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
        ),
        _record("trace-1", "2026-07-15 10:00:03", "node_run_summary", {}, provider=""),
    ]
    runtime_path = node_dir / "runtime_events.jsonl"
    with runtime_path.open("wb") as handle:
        handle.write((json.dumps(records[0]) + "\n").encode("utf-8"))
        handle.write(b"\x8dinvalid historical record\n")
        for record in records[1:]:
            handle.write((json.dumps(record) + "\n").encode("utf-8"))

    result = load_turn_token_stats(str(tmp_path))

    assert result["providers"]["demo"]["latest_turn"]["persisted_totals"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }
    assert result["diagnostics"] == [
        {
            "path": str(runtime_path),
            "invalid_utf8_lines": [2],
            "invalid_json_lines": [],
        }
    ]


def test_turn_token_stats_skips_invalid_json_record_and_reports_diagnostic(tmp_path):
    node_dir = tmp_path / "default" / "Agent1"
    node_dir.mkdir(parents=True)
    runtime_path = node_dir / "runtime_events.jsonl"
    runtime_path.write_text("not-json\n", encoding="utf-8")

    result = load_turn_token_stats(str(tmp_path))

    assert result == {
        "providers": {},
        "scope": {"graph_id": "", "hours": 0, "reset_at": ""},
        "available_graph_ids": [],
        "diagnostics": [
            {
                "path": str(runtime_path),
                "invalid_utf8_lines": [],
                "invalid_json_lines": [1],
            }
        ],
    }


def test_turn_token_stats_filters_graph_scope(tmp_path):
    for graph_id in ("default", "test"):
        node_dir = tmp_path / graph_id / "Agent1"
        node_dir.mkdir(parents=True)
        records = [
            _record("trace-" + graph_id, "2026-07-15 10:00:00", "node_run_start", {}, provider="", graph_id=graph_id),
            _record(
                "trace-" + graph_id,
                "2026-07-15 10:00:01",
                "provider_request_summary",
                {"request_index": 1},
                graph_id=graph_id,
            ),
            _record(
                "trace-" + graph_id,
                "2026-07-15 10:00:02",
                "node_run_summary",
                {"status": "completed"},
                graph_id=graph_id,
            ),
        ]
        (node_dir / "runtime_events.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    result = load_turn_token_stats(str(tmp_path), graph_id="test")

    assert result["scope"] == {"graph_id": "test", "hours": 0, "reset_at": ""}
    assert result["available_graph_ids"] == ["default", "test"]
    assert result["providers"]["demo"]["turn_count"] == 1
    assert result["providers"]["demo"]["latest_turn"]["graph_id"] == "test"


def test_turn_token_stats_includes_failed_terminal_without_usage(tmp_path):
    node_dir = tmp_path / "test" / "Agent1"
    node_dir.mkdir(parents=True)
    records = [
        _record("trace-failed", "2026-07-15 10:00:00", "node_run_start", {}, provider="", graph_id="test"),
        _record(
            "trace-failed",
            "2026-07-15 10:00:01",
            "node_run_summary",
            {"status": "failed", "error": "provider configuration failed"},
            provider="demo",
            graph_id="test",
        ),
    ]
    (node_dir / "runtime_events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    turn = load_turn_token_stats(str(tmp_path))["providers"]["demo"]["latest_turn"]

    assert turn["status"] == "failed"
    assert turn["error"] == "provider configuration failed"
    assert turn["request_count"] == 0
    assert turn["usage_status"] == "not_requested"


def test_turn_token_stats_reset_checkpoint_hides_older_turns(tmp_path):
    node_dir = tmp_path / "test" / "Agent1"
    node_dir.mkdir(parents=True)
    records = [
        _record("trace-old", "2026-07-21 10:00:00", "provider_request_summary", {"request_index": 1}, graph_id="test"),
        _record("trace-old", "2026-07-21 10:00:01", "node_run_summary", {"status": "completed"}, graph_id="test"),
        _record("trace-new", "2026-07-21 12:00:00", "provider_request_summary", {"request_index": 1}, graph_id="test"),
        _record("trace-new", "2026-07-21 12:00:01", "node_run_summary", {"status": "completed"}, graph_id="test"),
    ]
    (node_dir / "runtime_events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    result = load_turn_token_stats(
        str(tmp_path),
        graph_id="test",
        reset_at="2026-07-21T11:00:00+08:00",
    )

    provider = result["providers"]["demo"]
    assert provider["turn_count"] == 1
    assert provider["latest_turn"]["trace_id"] == "trace-new"
