import os
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="ClearLog.bat is Windows-only")
def test_clear_log_bat_only_removes_generated_logs(tmp_path):
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(workspace_root, "ClearLog.bat")
    memories_root = tmp_path / "memories"
    node_dir = memories_root / "graph" / "node"
    debug_dir = memories_root / "_http_debug"
    tasks_dir = node_dir / "tasks" / "task_123"
    tool_artifacts_dir = node_dir / "tool_artifacts" / "patches"
    archive_dir = node_dir / "archive" / "2026-07-23"
    node_dir.mkdir(parents=True)
    debug_dir.mkdir(parents=True)
    tasks_dir.mkdir(parents=True)
    tool_artifacts_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    deleted_paths = [
        node_dir / "runtime_events.jsonl",
        node_dir / "runtime_events.jsonl.lock",
        node_dir / "runtime.events.jsonl",
        node_dir / "runtime.events.jsonl.lock",
        node_dir / "runner.events.jsonl",
        node_dir / "runner.events.jsonl.lock",
        node_dir / "responses_payloads.jsonl",
        node_dir / "responses_payloads.jsonl.20260723_010203_000001.bak",
        node_dir / "context_artifacts.jsonl",
        node_dir / "context_artifacts.jsonl.lock",
        node_dir / "agent_context_history.json",
        node_dir / "agent_turn_context.json",
        node_dir / "analysis_verification.json",
        node_dir / "analysis_report.md",
        node_dir / "analysis_report_appendix.md",
        node_dir / "task_direction.json",
        node_dir / "task_direction.json.lock",
        node_dir / "log.txt",
        debug_dir / "provider_sse_chat.json",
        tasks_dir / "task_direction.json",
        tasks_dir / "task_direction.json.lock",
        tool_artifacts_dir / "tool-result.json",
        tool_artifacts_dir / "patch.diff",
    ]
    preserved_paths = [
        node_dir / "config.json",
        node_dir / "generated.png",
        node_dir / "long_term_memory.sqlite3",
        node_dir / "memory.md",
        node_dir / "messages.jsonl",
        node_dir / ".active-memory-state.json",
        node_dir / ".node-memory.lock",
        node_dir / "runtime_projection.json",
        archive_dir / "memory.md",
        archive_dir / "messages.jsonl",
    ]
    for path in deleted_paths + preserved_paths:
        path.write_text("test", encoding="utf-8")

    dry_run = subprocess.run(
        ["cmd.exe", "/c", script_path, "--root", str(memories_root), "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert dry_run.returncode == 0
    assert "Matched 23 log files" in dry_run.stdout
    assert all(path.exists() for path in deleted_paths)
    assert tasks_dir.exists()
    assert tool_artifacts_dir.exists()

    cleared = subprocess.run(
        ["cmd.exe", "/c", script_path, "--root", str(memories_root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert cleared.returncode == 0
    assert "Cleared 23 log files" in cleared.stdout
    assert all(not path.exists() for path in deleted_paths)
    assert all(path.exists() for path in preserved_paths)
    assert not (node_dir / "tasks").exists()
    assert not (node_dir / "tool_artifacts").exists()
    assert (node_dir / "archive").exists()

    refused = subprocess.run(
        ["cmd.exe", "/c", script_path, "--root", tmp_path.anchor, "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert refused.returncode == 2
    assert "refusing to clear logs from a filesystem root" in refused.stdout
