from src.message_protocol import envelope_text
from src.message_protocol import normalize_envelope
from src.message_protocol import normalize_message_envelope
from src.message_protocol import ResourcePart
from src.message_protocol import TextPart
from src.message_protocol import ToolCallPart


def test_tool_call_part_preserves_lifecycle_fields():
    envelope = normalize_envelope(
        {
            "role": "tool",
            "parts": [
                {
                    "type": "tool_call",
                    "call_id": "call-1",
                    "name": "read_file",
                    "provider": "unit",
                    "status": "completed",
                    "duration_ms": 12,
                    "arguments": {"filePath": "README.md"},
                    "result_preview": "ok",
                    "result_chars": 2,
                    "result_preview_truncated": False,
                    "result_tail_preview": "ok",
                    "result_tail_preview_truncated": False,
                    "diagnostics": ["image skipped"],
                }
            ],
        },
        default_role="tool",
    )

    part = envelope["parts"][0]
    assert envelope["role"] == "tool"
    assert part["type"] == "tool_call"
    assert part["call_id"] == "call-1"
    assert part["name"] == "read_file"
    assert part["provider"] == "unit"
    assert part["status"] == "completed"
    assert part["duration_ms"] == 12
    assert part["args"] == {"filePath": "README.md"}
    assert part["result_preview"] == "ok"
    assert part["result_chars"] == 2
    assert part["result_preview_truncated"] is False
    assert part["result_tail_preview"] == "ok"
    assert part["result_tail_preview_truncated"] is False
    assert part["diagnostics"] == ["image skipped"]


def test_typed_message_envelope_round_trips_normalized_parts():
    envelope = normalize_message_envelope(
        {
            "role": "assistant",
            "parts": [
                {"type": "text", "text": "hello"},
                {"type": "resource", "resource": {"kind": "image", "uri": "file://image.png"}},
                {"type": "tool_call", "name": "read_file", "status": "completed"},
            ],
            "trace_id": "trace-1",
        },
        default_role="assistant",
    )

    assert envelope.role == "assistant"
    assert envelope.trace_id == "trace-1"
    assert isinstance(envelope.parts[0], TextPart)
    assert isinstance(envelope.parts[1], ResourcePart)
    assert isinstance(envelope.parts[2], ToolCallPart)
    assert envelope.to_dict()["parts"][1]["resource"]["kind"] == "image"


def test_envelope_text_renders_tool_call_parts():
    text = envelope_text(
        {
            "role": "tool",
            "parts": [
                {
                    "type": "tool_call",
                    "call_id": "call-1",
                    "name": "execute_console_command",
                    "status": "completed",
                    "result_preview": '{"stdout": "hello"}',
                    "result_chars": 19,
                    "result_preview_truncated": False,
                }
            ],
        }
    )

    assert "Tool execute_console_command completed call_id=call-1" in text
    assert 'result_preview={"stdout": "hello"}' in text
    assert "result_chars=19" in text


def test_envelope_text_marks_empty_tool_call_parts_explicitly():
    text = envelope_text(
        {
            "role": "tool",
            "parts": [
                {
                    "type": "tool_call",
                    "call_id": "call-empty",
                    "name": "read_file",
                    "status": "completed",
                    "result_chars": 0,
                }
            ],
        }
    )

    assert "result_preview=(empty)" in text
    assert "result_chars=0" in text


def test_envelope_text_does_not_render_truncated_preview_as_tool_result():
    text = envelope_text(
        {
            "role": "tool",
            "parts": [
                {
                    "type": "tool_call",
                    "call_id": "call-large",
                    "name": "read_file",
                    "status": "completed",
                    "result_preview": '{"content": "partial',
                    "result_chars": 4096,
                    "result_preview_truncated": True,
                }
            ],
        }
    )

    assert "partial" not in text
    assert "result_preview omitted from markdown" in text
    assert "result_preview_truncated=true" in text
