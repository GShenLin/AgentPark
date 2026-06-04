import pytest

from src.web_backend.node_tool_history import build_tool_call_history_envelope


def test_build_tool_call_history_envelope_preserves_event_fields():
    envelope = build_tool_call_history_envelope(
        {
            "type": "tool_call_end",
            "call_id": "call-1",
            "name": "read_file",
            "provider": "unit",
            "status": "completed",
            "duration_ms": 5,
            "arguments": {"filePath": "README.md"},
            "result_preview": "ok",
            "diagnostics": ["image skipped"],
        }
    )

    assert envelope["role"] == "tool"
    assert envelope["id"] == "tool-call-1"
    part = envelope["parts"][0]
    assert part["type"] == "tool_call"
    assert part["call_id"] == "call-1"
    assert part["name"] == "read_file"
    assert part["provider"] == "unit"
    assert part["status"] == "completed"
    assert part["duration_ms"] == 5
    assert part["args"] == {"filePath": "README.md"}
    assert part["result_preview"] == "ok"
    assert part["diagnostics"] == ["image skipped"]


def test_build_tool_call_history_envelope_requires_call_id():
    with pytest.raises(ValueError, match="requires call_id"):
        build_tool_call_history_envelope({"type": "tool_call_end", "name": "read_file"})
