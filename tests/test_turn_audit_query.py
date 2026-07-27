from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.web_backend.turn_audit_query import get_turn_audit, list_turn_audits


TRACE_ID = "trace_20260727"
CALL_ID = "call_apply_patch"


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _build_complete_turn(tmp_path: Path) -> tuple[Path, Path]:
    memories_root = tmp_path / "memories"
    node_dir = memories_root / "default" / "Agent1"
    artifact_path = node_dir / "tool_artifacts" / "patches" / "change.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(
        json.dumps(
            {
                "schema": "agentpark.apply_patch.v1",
                "operations": [
                    {"type": "update", "path": "src/example.py"},
                    {"type": "add", "path": "tests/test_example.py"},
                ],
            }
        ),
        encoding="utf-8",
    )

    _write_jsonl(
        node_dir / "runtime_events.jsonl",
        [
            {
                "ts": "2026-07-27T08:00:00+08:00",
                "event": "runtime_notice",
                "trace_id": TRACE_ID,
                "runtime_event": {
                    "type": "runtime_notice",
                    "stage": "node_run_start",
                    "provider": "openai",
                },
            },
            {
                "ts": "2026-07-27T08:00:01+08:00",
                "event": "tool_call_start",
                "trace_id": TRACE_ID,
                "runtime_event": {
                    "call_id": CALL_ID,
                    "name": "apply_patch",
                    "arguments": {"patch": "*** Begin Patch"},
                },
            },
            {
                "ts": "2026-07-27T08:00:02+08:00",
                "event": "tool_call_end",
                "trace_id": TRACE_ID,
                "runtime_event": {
                    "call_id": CALL_ID,
                    "name": "apply_patch",
                    "status": "completed",
                    "duration_ms": 1000,
                    "result_preview": "Done",
                },
            },
            {
                "ts": "2026-07-27T08:00:03+08:00",
                "event": "runtime_notice",
                "trace_id": TRACE_ID,
                "runtime_event": {
                    "type": "runtime_notice",
                    "stage": "node_run_summary",
                    "provider": "openai",
                    "message": json.dumps(
                        {"status": "completed", "duration_ms": 3000}
                    ),
                },
            },
        ],
    )
    _write_jsonl(
        node_dir / "archive" / "2026-07-27" / "messages.jsonl",
        [
            {
                "id": "user-message",
                "trace_id": TRACE_ID,
                "role": "user",
                "created_at": "2026-07-27T08:00:00+08:00",
                "parts": [{"type": "text", "text": "请修改示例代码"}],
            },
            {
                "id": "assistant-message",
                "trace_id": TRACE_ID,
                "role": "assistant",
                "created_at": "2026-07-27T08:00:03+08:00",
                "parts": [{"type": "text", "text": "修改完成"}],
            },
            {
                "id": "other-trace-message",
                "trace_id": "another_trace",
                "role": "assistant",
                "created_at": "2026-07-27T08:00:04+08:00",
                "parts": [{"type": "text", "text": "不应出现在本轮审查中"}],
            },
        ],
    )
    tool_calls_path = tmp_path / "tool_calls.jsonl"
    _write_jsonl(
        tool_calls_path,
        [
            {
                "call_id": CALL_ID,
                "tool_name": "apply_patch",
                "tool_call_arguments": {"patch": "*** Begin Patch"},
                "result": json.dumps({"artifact_path": str(artifact_path)}),
                "result_preview": "Done",
            }
        ],
    )
    return memories_root, tool_calls_path


def test_turn_audit_joins_messages_tools_and_file_changes(tmp_path: Path) -> None:
    memories_root, tool_calls_path = _build_complete_turn(tmp_path)

    catalog = list_turn_audits(
        start_date_text="2026-07-26",
        end_date_text="2026-07-28",
        memories_root=str(memories_root),
    )

    assert catalog["start_date"] == "2026-07-26"
    assert catalog["end_date"] == "2026-07-28"
    assert catalog["available_graph_ids"] == ["default"]
    assert catalog["available_node_ids"] == ["Agent1"]
    assert len(catalog["turns"]) == 1
    assert catalog["turns"][0]["question"] == "请修改示例代码"
    assert catalog["turns"][0]["answer_preview"] == "修改完成"
    assert catalog["turns"][0]["audit_completeness"] == "complete"

    detail = get_turn_audit(
        trace_id=TRACE_ID,
        graph_id="default",
        node_id="Agent1",
        memories_root=str(memories_root),
        tool_calls_path=str(tool_calls_path),
    )

    assert detail["tool_calls"][0]["name"] == "apply_patch"
    assert detail["tool_calls"][0]["artifacts"][0]["data"]["schema"] == (
        "agentpark.apply_patch.v1"
    )
    assert detail["file_changes"] == [
        {
            "path": "src/example.py",
            "operation": "update",
            "call_id": CALL_ID,
            "artifact_path": str(
                memories_root
                / "default"
                / "Agent1"
                / "tool_artifacts"
                / "patches"
                / "change.json"
            ),
        },
        {
            "path": "tests/test_example.py",
            "operation": "add",
            "call_id": CALL_ID,
            "artifact_path": str(
                memories_root
                / "default"
                / "Agent1"
                / "tool_artifacts"
                / "patches"
                / "change.json"
            ),
        },
    ]
    assert {item["kind"] for item in detail["timeline"]} >= {
        "run_start",
        "user",
        "tool_call",
        "assistant",
        "run_end",
    }
    assert all(
        "不应出现在本轮审查中" not in str(item)
        for item in detail["timeline"]
    )


def test_turn_audit_marks_finished_but_incomplete_chain_partial(tmp_path: Path) -> None:
    memories_root = tmp_path / "memories"
    node_dir = memories_root / "default" / "Agent1"
    _write_jsonl(
        node_dir / "runtime_events.jsonl",
        [
            {
                "ts": "2026-07-27T09:00:00+08:00",
                "event": "tool_call_start",
                "trace_id": TRACE_ID,
                "runtime_event": {"call_id": CALL_ID, "name": "shell_command"},
            },
            {
                "ts": "2026-07-27T09:00:01+08:00",
                "event": "runtime_notice",
                "trace_id": TRACE_ID,
                "runtime_event": {
                    "type": "runtime_notice",
                    "stage": "node_run_summary",
                    "message": {"status": "completed", "duration_ms": 1000},
                },
            },
        ],
    )
    _write_jsonl(
        node_dir / "archive" / "2026-07-27" / "messages.jsonl",
        [
            {
                "id": "user-message",
                "trace_id": TRACE_ID,
                "role": "user",
                "created_at": "2026-07-27T09:00:00+08:00",
                "parts": [{"type": "text", "text": "执行命令"}],
            }
        ],
    )

    catalog = list_turn_audits(
        start_date_text="2026-07-27",
        end_date_text="2026-07-27",
        memories_root=str(memories_root),
    )

    assert catalog["turns"][0]["audit_completeness"] == "partial"


@pytest.mark.parametrize("value", ["", "2026/07/27", "not-a-date"])
def test_turn_audit_rejects_invalid_date(value: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        list_turn_audits(
            start_date_text=value,
            end_date_text="2026-07-27",
            memories_root=str(tmp_path),
        )


def test_turn_audit_rejects_reversed_date_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="start_date"):
        list_turn_audits(
            start_date_text="2026-07-28",
            end_date_text="2026-07-27",
            memories_root=str(tmp_path),
        )
