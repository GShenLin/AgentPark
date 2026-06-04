import pytest

from src.web_backend.runtime_event_store import append_runtime_event
from src.web_backend.runtime_event_store import clear_runtime_event
from src.web_backend.runtime_event_store import normalize_runtime_event


def test_runtime_event_store_groups_tool_lifecycle_by_call_id():
    payload = {}

    append_runtime_event(
        payload,
        {
            "type": "tool_call_start",
            "name": "read_file",
            "call_id": "call-1",
            "provider": "unit",
            "arguments": {"filePath": "README.md"},
        },
    )
    append_runtime_event(
        payload,
        {
            "type": "tool_call_end",
            "name": "read_file",
            "call_id": "call-1",
            "provider": "unit",
            "status": "completed",
            "duration_ms": 12,
            "result_preview": "ok",
            "diagnostics": ["image skipped"],
        },
    )

    calls = payload.get("runtime_tool_calls")
    assert isinstance(calls, list)
    assert len(calls) == 1
    assert calls[0]["call_id"] == "call-1"
    assert calls[0]["name"] == "read_file"
    assert calls[0]["status"] == "completed"
    assert calls[0]["arguments"] == {"filePath": "README.md"}
    assert calls[0]["duration_ms"] == 12
    assert calls[0]["result_preview"] == "ok"
    assert calls[0]["diagnostics"] == ["image skipped"]


def test_runtime_event_store_keeps_notice_out_of_grouped_tool_calls():
    payload = {}

    append_runtime_event(
        payload,
        {
            "type": "runtime_notice",
            "message": "Calling tool: read_file",
            "source": "tool_call",
            "name": "read_file",
            "call_id": "call-1",
        },
    )

    assert payload["last_runtime_event"]["type"] == "runtime_notice"
    assert payload["runtime_events"][-1]["message"] == "Calling tool: read_file"
    assert "runtime_tool_calls" not in payload


def test_runtime_event_store_reset_clears_grouped_tool_calls():
    payload = {}
    append_runtime_event(
        payload,
        {
            "type": "tool_call_start",
            "name": "read_file",
            "call_id": "call-1",
            "provider": "unit",
            "arguments": {},
        },
    )

    clear_runtime_event(payload, reset_history=True)

    assert "last_runtime_event" not in payload
    assert "runtime_events" not in payload
    assert "runtime_tool_calls" not in payload


def test_runtime_event_store_normalizes_runtime_notice_boundary():
    normalized = normalize_runtime_event(
        {
            "type": " runtime_notice ",
            "message": "  retrying  ",
            "source": "",
            "stage": " post_json_retry ",
            "provider": " doubao ",
            "unexpected": "drop me",
        }
    )

    assert normalized == {
        "type": "runtime_notice",
        "message": "retrying",
        "source": "runtime",
        "stage": "post_json_retry",
        "provider": "doubao",
    }


def test_runtime_event_store_normalizes_tool_event_boundary():
    payload = {}

    append_runtime_event(
        payload,
        {
            "type": "TOOL_CALL_END",
            "name": "",
            "call_id": " call-1 ",
            "provider": " unit ",
            "status": "",
            "duration_ms": 12.7,
            "diagnostics": (" diag ", "", None),
            "result_preview": " ok ",
            "unexpected": "drop me",
        },
    )

    event = payload["last_runtime_event"]
    assert event == {
        "type": "tool_call_end",
        "name": "tool",
        "call_id": "call-1",
        "provider": "unit",
        "status": "completed",
        "duration_ms": 13,
        "result_preview": "ok",
        "diagnostics": ["diag"],
    }
    call = payload["runtime_tool_calls"][0]
    assert call["duration_ms"] == 13
    assert call["diagnostics"] == ["diag"]


def test_runtime_event_store_rejects_invalid_runtime_events():
    with pytest.raises(ValueError, match="unsupported runtime event type"):
        normalize_runtime_event({"type": "unknown"})

    with pytest.raises(ValueError, match="runtime_notice requires message"):
        normalize_runtime_event({"type": "runtime_notice", "message": ""})

    with pytest.raises(ValueError, match="tool runtime event requires call_id"):
        normalize_runtime_event({"type": "tool_call_start", "name": "read_file"})
