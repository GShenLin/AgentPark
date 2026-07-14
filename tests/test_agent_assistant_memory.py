import json

from nodes.agent_assistant_memory import persist_assistant_progress
from nodes.agent_assistant_memory import persist_provider_turn_metadata


def test_persist_assistant_progress_writes_per_turn_metadata_sidecar(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"

    assert persist_assistant_progress(
        message={
            "role": "assistant_progress",
            "content": "I will inspect the file.",
            "context_policy": "exclude",
            "tool_calls": [{"id": "call-1", "function": {"name": "read_file"}}],
            "response_metadata": {
                "protocol": "responses",
                "response": {"id": "resp-tool", "status": "completed"},
                "output_items": [{"type": "function_call", "call_id": "call-1"}],
            },
        },
        memory_path=str(memory_path),
        messages_path=str(messages_path),
    )

    records = [json.loads(line) for line in messages_path.read_text(encoding="utf-8").splitlines()]
    assert [record["role"] for record in records] == ["assistant_progress", "metadata"]
    metadata = records[1]["parts"][0]["data"]
    assert metadata["scope"] == "provider_turn"
    assert metadata["target"] == {"type": "message", "message_id": records[0]["id"]}
    assert metadata["provider_turn_id"] == "resp-tool"
    assert metadata["response_metadata"]["response"]["id"] == "resp-tool"


def test_persist_provider_turn_metadata_targets_tool_calls_without_blank_progress(tmp_path):
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"

    assert persist_provider_turn_metadata(
        message={
            "role": "provider_turn",
            "tool_calls": [{"id": "call-1", "function": {"name": "read_file"}}],
            "response_metadata": {
                "protocol": "responses",
                "response": {"id": "resp-tool", "status": "completed"},
                "output_items": [{"type": "reasoning"}, {"type": "function_call", "call_id": "call-1"}],
            },
        },
        memory_path=str(memory_path),
        messages_path=str(messages_path),
    )

    records = [json.loads(line) for line in messages_path.read_text(encoding="utf-8").splitlines()]
    assert [record["role"] for record in records] == ["metadata"]
    metadata = records[0]["parts"][0]["data"]
    assert metadata["scope"] == "provider_turn"
    assert metadata["target"] == {"type": "tool_calls", "call_ids": ["call-1"]}
    assert metadata["provider_turn_id"] == "resp-tool"
