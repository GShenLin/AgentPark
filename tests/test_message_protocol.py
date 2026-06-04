from src.message_protocol import normalize_envelope


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
    assert part["diagnostics"] == ["image skipped"]
