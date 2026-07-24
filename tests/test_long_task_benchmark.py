import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import benchmark_long_task
from scripts.benchmark_long_task import summarize_events
from scripts.long_task_benchmark_artifacts import EventJournal
from scripts.long_task_benchmark_artifacts import resolve_agent_profile
from scripts.long_task_benchmark_artifacts import rewrite_event_journal


def _record(elapsed_ms, event):
    return {"elapsed_ms": elapsed_ms, "event": event}


def test_benchmark_summary_counts_model_turns_tools_and_usage():
    events = [
        _record(1, {"type": "tool_call_start", "name": "read_file"}),
        _record(2, {"type": "tool_call_end", "name": "read_file", "status": "completed"}),
        _record(
            3,
            {
                "type": "runtime_notice",
                "stage": "provider_request_summary",
                "message": '{"request_index":1,"approx_input_tokens":10,"tools_included_count":3}',
            },
        ),
        _record(
            4,
            {
                "type": "runtime_notice",
                "stage": "provider_request_completed",
                "message": (
                    '{"request_index":1,"usage":{"input_tokens":12,"output_tokens":3,'
                    '"total_tokens":15,"cached_input_tokens":8,"reasoning_output_tokens":2}}'
                ),
            },
        ),
        _record(
            5,
            {
                "type": "runtime_notice",
                "stage": "provider_request_completed",
                "message": '{"request_index":2}',
            },
        ),
        _record(
            6,
            {
                "type": "runtime_notice",
                "stage": "provider_gateway_request",
                "message": '{"request_index":1,"requested_model":"runtime","provider_model":"actual"}',
            },
        ),
    ]

    summary = summarize_events(events, duration_ms=20, output="done")

    assert summary["model_turn_count"] == 2
    assert summary["usage_model_turn_count"] == 1
    assert summary["missing_usage_model_turn_count"] == 1
    assert summary["tool_call_start_count"] == 1
    assert summary["tool_call_end_count"] == 1
    assert summary["usage"]["total_tokens"] == 15
    assert summary["output_chars"] == 4
    assert summary["provider_gateway_requests"][0]["provider_model"] == "actual"


def test_failed_benchmark_persists_events_summary_and_error(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("run", encoding="utf-8")
    result_dir = tmp_path / "result"

    class FailingNode:
        def on_input(self, _prompt, context):
            context["stream_callback"]({"type": "tool_call_start", "name": "inspect"})
            raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(benchmark_long_task, "CodexNode", FailingNode)
    monkeypatch.setattr(
        benchmark_long_task,
        "git_workspace_snapshot",
        lambda _workspace: {"revision": "test", "clean": True, "status": [], "changed_paths": []},
    )
    args = argparse.Namespace(
        node_type="codex",
        workspace=str(workspace),
        prompt_file=str(prompt),
        result_dir=str(result_dir),
        provider_id="GPT_Official",
        profile=str(tmp_path / "unused.json"),
    )

    with pytest.raises(RuntimeError, match="upstream unavailable"):
        benchmark_long_task.run_benchmark(args)

    payload = benchmark_long_task._read_json(result_dir / "result.json")
    assert payload["status"] == "error"
    assert payload["error"] == "RuntimeError: upstream unavailable"
    assert payload["summary"]["tool_call_start_count"] == 1
    assert payload["events"][0]["event"]["name"] == "inspect"
    journal = (result_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(journal) == 1


def test_event_journal_refuses_to_mix_runs(tmp_path):
    path = tmp_path / "events.jsonl"
    journal = EventJournal(path)
    journal.append({"event": {"type": "started"}})

    with pytest.raises(FileExistsError, match="already exists"):
        EventJournal(path)


def test_event_journal_keeps_concurrent_callback_records_atomic(tmp_path):
    path = tmp_path / "events.jsonl"
    journal = EventJournal(path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: journal.append({"index": index}), range(200)))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert sorted(record["index"] for record in records) == list(range(200))


def test_event_journal_can_be_rebuilt_from_authoritative_result(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"broken"\n', encoding="utf-8")

    rewrite_event_journal(path, [{"index": 1}, {"index": 2}])

    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == [
        {"index": 1},
        {"index": 2},
    ]


def test_agent_profile_accepts_explicit_path_or_project_profile_id(tmp_path):
    project_root = tmp_path / "project"
    profile = project_root / "agent" / "GPT1.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}", encoding="utf-8")

    assert resolve_agent_profile(str(profile), project_root=project_root) == profile.resolve()
    assert resolve_agent_profile("GPT1", project_root=project_root) == profile.resolve()
