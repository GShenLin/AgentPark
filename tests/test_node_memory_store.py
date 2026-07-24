import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.message_protocol import build_text_envelope
from src.web_backend.node_memory_store import NodeMemoryPersistenceError
from src.web_backend.node_memory_store import append_node_memory_entry
from src.web_backend.node_memory_store import append_node_tool_call_entry
from src.web_backend.node_memory_store import current_node_memory_paths
from src.web_backend.node_memory_store import ensure_node_memory_files
from src.web_backend.node_memory_store import load_recent_node_memory_records
from src.web_backend.node_memory_store import load_latest_node_memory_turn
from src.web_backend.node_memory_store import read_node_memory_text
from src.web_backend.node_instance_runtime import _latest_turn_progress_summary, _select_latest_turn_records


def test_append_node_memory_entry_writes_markdown_and_jsonl(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    message = {
        "id": "msg-1",
        "role": "assistant",
        "parts": [{"type": "text", "text": "hello"}],
        "created_at": "2026-06-21 10:11:12.000000",
    }

    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "assistant",
        message,
    )

    markdown = memory_path.read_text(encoding="utf-8")
    assert "<!-- message_id: msg-1 -->" in markdown
    assert "**[2026-06-21 10:11:12] assistant**: hello" in markdown
    lines = messages_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["id"] == "msg-1"
    assert payload["role"] == "assistant"
    assert payload["parts"][0]["text"] == "hello"


def test_append_node_tool_call_entry_writes_structured_tool_history(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"

    append_node_tool_call_entry(
        str(memory_path),
        str(messages_path),
        {
            "type": "tool_call_end",
            "call_id": "call-1",
            "name": "read_file",
            "status": "completed",
            "result_preview": "ok",
            "result_chars": 2,
            "result_preview_truncated": False,
            "result_tail_preview": "ok",
            "result_tail_preview_truncated": False,
        },
    )

    current = current_node_memory_paths(str(memory_path), str(messages_path))
    payload = json.loads(open(current["messages_path"], encoding="utf-8").read().splitlines()[0])
    assert payload["role"] == "tool"
    assert payload["parts"][0]["type"] == "tool_call"
    assert payload["parts"][0]["call_id"] == "call-1"
    assert payload["parts"][0]["result_preview"] == "ok"
    assert payload["parts"][0]["result_chars"] == 2
    assert payload["parts"][0]["result_preview_truncated"] is False
    assert payload["parts"][0]["result_tail_preview"] == "ok"
    assert payload["parts"][0]["result_tail_preview_truncated"] is False
    markdown = open(current["memory_path"], encoding="utf-8").read()
    assert f"<!-- message_id: {payload['id']} -->" in markdown
    assert "Tool read_file completed call_id=call-1" in markdown
    assert "result_preview=ok" in markdown
    assert "result_chars=2" in markdown


def test_load_recent_node_memory_records_filters_roles_before_applying_limit(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    for role, message_id in (("user", "u1"), ("assistant", "a1"), ("metadata", "m1"), ("user", "u2")):
        append_node_memory_entry(
            str(memory_path),
            str(messages_path),
            role,
            {"id": message_id, "role": role, "parts": [{"type": "text", "text": message_id}]},
        )

    records = load_recent_node_memory_records(
        str(memory_path),
        str(messages_path),
        limit=2,
        roles={"user", "assistant"},
    )

    assert [record["id"] for record in records] == ["a1", "u2"]


def test_load_latest_node_memory_turn_returns_complete_newest_turn(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    for role, message_id in (
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "u2"),
        ("assistant_progress", "p2"),
        ("tool", "t2"),
        ("assistant", "a2"),
        ("metadata", "m2"),
    ):
        append_node_memory_entry(
            str(memory_path),
            str(messages_path),
            role,
            {"id": message_id, "role": role, "parts": [{"type": "text", "text": message_id}]},
        )

    records, history_complete = load_latest_node_memory_turn(str(memory_path), str(messages_path))

    assert [record["id"] for record in records] == ["u2", "p2", "t2", "a2", "m2"]
    assert history_complete is False


def test_load_latest_node_memory_turn_reports_complete_single_turn(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    for role, message_id in (("user", "u1"), ("assistant", "a1")):
        append_node_memory_entry(
            str(memory_path),
            str(messages_path),
            role,
            {"id": message_id, "role": role, "parts": [{"type": "text", "text": message_id}]},
        )

    records, history_complete = load_latest_node_memory_turn(str(memory_path), str(messages_path))

    assert [record["id"] for record in records] == ["u1", "a1"]
    assert history_complete is True


def test_latest_turn_reads_only_the_committed_prefix_during_next_append(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "user",
        {"id": "u1", "role": "user", "parts": [{"type": "text", "text": "ready"}]},
    )
    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "assistant",
        {"id": "a1", "role": "assistant", "parts": [{"type": "text", "text": "done"}]},
    )

    with messages_path.open("ab") as handle:
        handle.write(b'{"id":"partial","role":"assistant"')

    records, history_complete = load_latest_node_memory_turn(str(memory_path), str(messages_path))

    assert [record["id"] for record in records] == ["u1", "a1"]
    assert history_complete is True


def test_load_latest_node_memory_turn_defers_unrequested_large_metadata(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    records = [
        {
            "id": "u1",
            "role": "user",
            "parts": [{"type": "text", "text": "question"}],
            "created_at": "2026-07-16 10:00:00.000000",
        },
        {
            "id": "a1",
            "role": "assistant",
            "parts": [{"type": "text", "text": "answer"}],
            "created_at": "2026-07-16 10:00:01.000000",
        },
        {
            "id": "m1",
            "role": "metadata",
            "parts": [{"type": "data", "data": {"payload": "x" * (512 * 1024)}}],
            "created_at": "2026-07-16 10:00:02.000000",
        },
    ]
    messages_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

    latest, history_complete = load_latest_node_memory_turn(
        str(memory_path),
        str(messages_path),
        materialize_roles={"user", "assistant"},
    )

    assert history_complete is True
    assert latest[-1] == {"id": "", "role": "metadata", "parts": [], "created_at": "", "_deferred": True}
    assert [item["id"] for item in _select_latest_turn_records(latest, "latest_turn")] == ["u1", "a1"]


def test_latest_turn_lazy_modes_split_summary_progress_and_metadata():
    records = [
        {"id": "u1", "role": "user"},
        {"id": "p1", "role": "assistant_progress"},
        {"id": "t1", "role": "tool"},
        {"id": "a1", "role": "assistant"},
        {"id": "m1", "role": "metadata"},
    ]

    assert [item["id"] for item in _select_latest_turn_records(records, "latest_turn")] == ["u1", "a1"]
    assert [item["id"] for item in _select_latest_turn_records(records, "latest_turn_progress")] == [
        "u1",
        "p1",
        "t1",
        "a1",
    ]
    assert [item["id"] for item in _select_latest_turn_records(records, "latest_turn_metadata")] == [
        "u1",
        "a1",
        "m1",
    ]


def test_latest_turn_progress_summary_counts_hidden_items_and_tool_parts():
    records = [
        {"id": "old-u", "role": "user"},
        {"id": "old-p", "role": "assistant_progress"},
        {"id": "old-a", "role": "assistant"},
        {"id": "u1", "role": "user"},
        {"id": "p1", "role": "assistant_progress", "parts": [{"type": "text", "text": "thinking"}]},
        {"id": "a-mid", "role": "assistant", "parts": [{"type": "text", "text": "I will inspect"}]},
        {
            "id": "t1",
            "role": "tool",
            "parts": [
                {"type": "tool_call", "name": "read_file"},
                {"type": "tool_call", "name": "search"},
            ],
        },
        {"id": "a1", "role": "assistant"},
        {"id": "m1", "role": "metadata"},
    ]

    assert _latest_turn_progress_summary(records) == {"item_count": 3, "tool_count": 2}


def test_latest_turn_progress_summary_counts_inflight_progress_without_final_response():
    records = [
        {"id": "u1", "role": "user"},
        {"id": "p1", "role": "assistant_progress"},
        {"id": "t1", "role": "tool", "parts": [{"type": "tool_call", "name": "read_file"}]},
    ]

    assert _latest_turn_progress_summary(records) == {"item_count": 2, "tool_count": 1}


def test_latest_turn_progress_mode_keeps_inflight_progress_without_final_assistant():
    records = [
        {"id": "u1", "role": "user"},
        {"id": "p1", "role": "assistant_progress"},
        {"id": "t1", "role": "tool"},
    ]

    assert [item["id"] for item in _select_latest_turn_records(records, "latest_turn")] == ["u1"]
    assert [item["id"] for item in _select_latest_turn_records(records, "latest_turn_progress")] == [
        "u1",
        "p1",
        "t1",
    ]


def test_latest_turn_uses_system_message_as_terminal_response():
    records = [
        {"id": "u1", "role": "user"},
        {"id": "p1", "role": "assistant_progress"},
        {"id": "t1", "role": "tool"},
        {"id": "e1", "role": "system"},
    ]

    assert [item["id"] for item in _select_latest_turn_records(records, "latest_turn")] == ["u1", "e1"]
    assert [item["id"] for item in _select_latest_turn_records(records, "latest_turn_progress")] == [
        "u1",
        "p1",
        "t1",
        "e1",
    ]


def test_records_over_limit_archive_old_entries_and_keep_recent_active(tmp_path, monkeypatch):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr("src.web_backend.node_memory_store._read_max_active_memory_entries", lambda: 2)

    for index, date_text in enumerate(["2026-06-20", "2026-06-21", "2026-06-22"], start=1):
        append_node_memory_entry(
            str(memory_path),
            str(messages_path),
            "user",
            {
                "id": f"msg-{index}",
                "role": "user",
                "parts": [{"type": "text", "text": f"hello {index}"}],
                "created_at": f"{date_text} 08:00:00.000000",
            },
        )

    assert [json.loads(line)["id"] for line in messages_path.read_text(encoding="utf-8").splitlines()] == [
        "msg-2",
        "msg-3",
    ]
    archived_messages = tmp_path / "archive" / "2026-06-20" / "messages.jsonl"
    assert [json.loads(line)["id"] for line in archived_messages.read_text(encoding="utf-8").splitlines()] == [
        "msg-1"
    ]

    records = load_recent_node_memory_records(str(memory_path), str(messages_path), limit=2)
    assert [item["id"] for item in records] == ["msg-2", "msg-3"]
    text = read_node_memory_text(str(memory_path), str(messages_path), max_chars=5000)
    assert "<!-- message_id: msg-1 -->" in text
    assert "<!-- message_id: msg-2 -->" in text
    assert "<!-- message_id: msg-3 -->" in text


def test_active_limit_does_not_split_or_rewrite_an_inflight_user_turn(tmp_path, monkeypatch):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr("src.web_backend.node_memory_store._read_max_active_memory_entries", lambda: 3)

    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "user",
        {"id": "u1", "role": "user", "parts": [{"type": "text", "text": "task"}]},
    )
    for index in range(5):
        append_node_memory_entry(
            str(memory_path),
            str(messages_path),
            "tool",
            {
                "id": f"t{index}",
                "role": "tool",
                "parts": [{"type": "text", "text": "x" * 1024}],
            },
        )

    active_ids = [json.loads(line)["id"] for line in messages_path.read_text(encoding="utf-8").splitlines()]
    assert active_ids == ["u1", "t0", "t1", "t2", "t3", "t4"]
    assert not (tmp_path / "archive").exists()

    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "user",
        {"id": "u2", "role": "user", "parts": [{"type": "text", "text": "next"}]},
    )

    active_ids = [json.loads(line)["id"] for line in messages_path.read_text(encoding="utf-8").splitlines()]
    assert active_ids == ["u2"]
    archived = list((tmp_path / "archive").rglob("messages.jsonl"))
    archived_ids = [
        json.loads(line)["id"]
        for path in archived
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert archived_ids == ["u1", "t0", "t1", "t2", "t3", "t4"]


def test_read_node_memory_text_can_read_full_history(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    first_payload = "a" * 15000
    second_payload = "b" * 15000

    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "user",
        build_text_envelope(first_payload, role="user"),
    )
    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "assistant",
        build_text_envelope(second_payload, role="assistant"),
    )

    limited = read_node_memory_text(str(memory_path), str(messages_path), max_chars=20000)
    full = read_node_memory_text(str(memory_path), str(messages_path), max_chars=None)

    assert len(limited) == 20000
    assert first_payload in full
    assert second_payload in full
    assert len(full) > 30000


def test_concurrent_node_memory_appends_keep_all_records(tmp_path, monkeypatch):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr("src.web_backend.node_memory_store._read_max_active_memory_entries", lambda: 200)

    def append(index):
        append_node_memory_entry(
            str(memory_path),
            str(messages_path),
            "assistant",
            {
                "id": f"msg-{index}",
                "role": "assistant",
                "parts": [{"type": "text", "text": f"hello {index}"}],
                "created_at": "2026-06-22 08:00:00.000000",
            },
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(append, range(50)))

    records = [json.loads(line) for line in messages_path.read_text(encoding="utf-8").splitlines()]
    assert {item["id"] for item in records} == {f"msg-{index}" for index in range(50)}
    markdown = memory_path.read_text(encoding="utf-8")
    for index in range(50):
        assert f"<!-- message_id: msg-{index} -->" in markdown
    assert not list(tmp_path.glob("*.tmp"))


def test_concurrent_node_memory_appends_with_archive_keep_all_records(tmp_path, monkeypatch):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    monkeypatch.setattr("src.web_backend.node_memory_store._read_max_active_memory_entries", lambda: 5)

    def append(index):
        append_node_memory_entry(
            str(memory_path),
            str(messages_path),
            "user",
            {
                "id": f"msg-{index}",
                "role": "user",
                "parts": [{"type": "text", "text": f"hello {index}"}],
                "created_at": "2026-06-22 08:00:00.000000",
            },
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(append, range(30)))

    active_records = [json.loads(line) for line in messages_path.read_text(encoding="utf-8").splitlines()]
    archived_messages = tmp_path / "archive" / "2026-06-22" / "messages.jsonl"
    archived_records = [json.loads(line) for line in archived_messages.read_text(encoding="utf-8").splitlines()]
    all_ids = [item["id"] for item in active_records + archived_records]

    assert len(active_records) == 5
    assert set(all_ids) == {f"msg-{index}" for index in range(30)}
    assert len(all_ids) == len(set(all_ids))
    assert not list(tmp_path.rglob("*.tmp"))


def test_append_node_memory_entry_reports_all_target_failures():
    with pytest.raises(NodeMemoryPersistenceError) as exc:
        append_node_memory_entry("", "", "assistant", build_text_envelope("hello", role="assistant"))

    assert [failure.target for failure in exc.value.failures] == ["messages", "memory"]
    assert "path is empty" in str(exc.value)


def test_ensure_node_memory_files_reports_empty_paths():
    with pytest.raises(NodeMemoryPersistenceError) as exc:
        ensure_node_memory_files("", "")

    assert [failure.target for failure in exc.value.failures] == ["memory", "messages"]


def test_read_node_memory_text_reports_unreadable_memory_file(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    memory_path.write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(NodeMemoryPersistenceError) as exc:
        read_node_memory_text(str(memory_path), str(messages_path), max_chars=5000)

    assert exc.value.failures[0].target == "memory"
    assert "UnicodeDecodeError" in exc.value.failures[0].error


def test_load_recent_node_memory_records_reports_invalid_jsonl(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    memory_path.write_text("", encoding="utf-8")
    messages_path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(NodeMemoryPersistenceError) as exc:
        load_recent_node_memory_records(str(memory_path), str(messages_path), limit=10)

    assert exc.value.failures[0].target in {"messages", "migration"}
    assert "invalid JSONL record" in exc.value.failures[0].error
