import json

import pytest

from src.message_protocol import build_text_envelope
from src.web_backend.node_memory_store import NodeMemoryPersistenceError
from src.web_backend.node_memory_store import append_node_memory_entry
from src.web_backend.node_memory_store import append_node_tool_call_entry
from src.web_backend.node_memory_store import ensure_node_memory_files


def test_append_node_memory_entry_writes_markdown_and_jsonl(tmp_path):
    memory_path = tmp_path / "agent.md"
    messages_path = tmp_path / "messages.jsonl"

    append_node_memory_entry(
        str(memory_path),
        str(messages_path),
        "assistant",
        build_text_envelope("hello", role="assistant"),
    )

    assert "**" in memory_path.read_text(encoding="utf-8")
    assert "assistant" in memory_path.read_text(encoding="utf-8")
    assert "hello" in memory_path.read_text(encoding="utf-8")
    lines = messages_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["role"] == "assistant"
    assert payload["parts"][0]["text"] == "hello"


def test_append_node_tool_call_entry_writes_structured_tool_history(tmp_path):
    memory_path = tmp_path / "agent.md"
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
        },
    )

    payload = json.loads(messages_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["role"] == "tool"
    assert payload["parts"][0]["type"] == "tool_call"
    assert payload["parts"][0]["call_id"] == "call-1"


def test_append_node_memory_entry_reports_all_target_failures():
    with pytest.raises(NodeMemoryPersistenceError) as exc:
        append_node_memory_entry("", "", "assistant", build_text_envelope("hello", role="assistant"))

    assert [failure.target for failure in exc.value.failures] == ["messages", "memory"]
    assert "path is empty" in str(exc.value)


def test_ensure_node_memory_files_reports_empty_paths():
    with pytest.raises(NodeMemoryPersistenceError) as exc:
        ensure_node_memory_files("", "")

    assert [failure.target for failure in exc.value.failures] == ["memory", "messages"]
