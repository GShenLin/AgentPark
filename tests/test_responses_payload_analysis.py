import json


def test_analyze_responses_payload_log_reports_codex_like_shape(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    record = {
        "stage": "openai_responses_request_payload",
        "request_index": 1,
        "payload": {
            "model": "gpt-test",
            "instructions": "You are Codex-like.",
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {"type": "input_text", "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>"}
                    ],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>"}],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello"}],
                },
            ],
        },
        "request_summary": {"responses_mode": "item_level", "context_update_mode": "full"},
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert analysis["exists"] is True
    assert analysis["record_count"] == 1
    assert analysis["gaps"] == []
    request = analysis["requests"][0]
    assert request["instructions_present"] is True
    assert request["instructions_chars"] == len("You are Codex-like.")
    assert request["input_items"][0]["context_kinds"] == ["permissions"]
    assert request["input_items"][1]["context_kinds"] == ["environment"]
    assert request["summary"]["context_update_mode"] == "full"


def test_analyze_responses_payload_log_allows_system_input_but_flags_missing_instructions(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    record = {
        "request_index": 1,
        "payload": {
            "model": "gpt-test",
            "input": [
                {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "system prompt"}]},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]},
            ],
        },
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert any("payload.instructions is absent" in gap for gap in analysis["gaps"])
    assert not any("system role item" in gap for gap in analysis["gaps"])


def test_analyze_responses_payload_log_flags_missing_followup_instructions(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    records = [
        {
            "request_index": 1,
            "payload": {
                "model": "gpt-test",
                "instructions": "You are Codex-like.",
                "input": [
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>",
                            }
                        ],
                    },
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>",
                            }
                        ],
                    },
                ],
            },
        },
        {
            "request_index": 2,
            "payload": {
                "model": "gpt-test",
                "input": [
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>",
                            }
                        ],
                    },
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>",
                            }
                        ],
                    },
                ],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert any("request 2 lacks payload.instructions" in gap for gap in analysis["gaps"])


def test_analyze_responses_payload_log_flags_duplicate_runtime_context(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    context_items = [
        {
            "type": "message",
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>",
                }
            ],
        },
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>",
                }
            ],
        },
    ]
    records = [
        {
            "request_index": 1,
            "payload": {
                "model": "gpt-test",
                "instructions": "You are Codex-like.",
                "input": [*context_items, {"type": "message", "role": "user", "content": []}],
            },
        },
        {
            "request_index": 2,
            "payload": {
                "model": "gpt-test",
                "instructions": "You are Codex-like.",
                "input": [*context_items, *context_items, {"type": "message", "role": "user", "content": []}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert any("repeats permissions context 2 times" in gap for gap in analysis["gaps"])
    assert any("repeats environment context 2 times" in gap for gap in analysis["gaps"])


def test_analyze_responses_payload_log_flags_split_contextual_user_context(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    record = {
        "request_index": 1,
        "payload": {
            "model": "gpt-test",
            "instructions": "You are Codex-like.",
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>",
                        }
                    ],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>",
                        }
                    ],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "# AGENTS.md instructions\n\n<INSTRUCTIONS>\nUse rg.\n</INSTRUCTIONS>",
                        }
                    ],
                },
            ],
        },
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert any("splits contextual user runtime context" in gap for gap in analysis["gaps"])


def test_analyze_responses_payload_log_flags_missing_codex_tool_request_fields(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    record = {
        "request_index": 1,
        "payload": {
            "model": "gpt-test",
            "instructions": "You are Codex-like.",
            "tools": [{"type": "function", "name": "echo_tool", "parameters": {"type": "object"}}],
            "reasoning": {"effort": "medium"},
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>",
                        }
                    ],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>",
                        }
                    ],
                },
            ],
        },
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert any("tool_choice=auto" in gap for gap in analysis["gaps"])
    assert any("parallel_tool_calls=true" in gap for gap in analysis["gaps"])
    assert any("reasoning.encrypted_content" in gap for gap in analysis["gaps"])


def test_analyze_responses_payload_log_flags_duplicate_context_parts(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    record = {
        "request_index": 1,
        "payload": {
            "model": "gpt-test",
            "instructions": "You are Codex-like.",
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>",
                        },
                        {"type": "input_text", "text": "Operational memory for this node:\n- one"},
                        {"type": "input_text", "text": "Operational memory for this node:\n- two"},
                    ],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>",
                        }
                    ],
                },
            ],
        },
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert any("repeats operational_memory context parts 2 times" in gap for gap in analysis["gaps"])


def test_analyze_responses_payload_log_accepts_codex_tool_request_fields(tmp_path):
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    path = tmp_path / "responses_payloads.jsonl"
    record = {
        "request_index": 1,
        "payload": {
            "model": "gpt-test",
            "instructions": "You are Codex-like.",
            "tools": [{"type": "function", "name": "echo_tool", "parameters": {"type": "object"}}],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "reasoning": {"effort": "medium"},
            "include": ["reasoning.encrypted_content"],
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<permissions instructions>\nNo sandbox.\n</permissions instructions>",
                        }
                    ],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>",
                        }
                    ],
                },
            ],
        },
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    analysis = analyze_responses_payload_log(str(path))

    assert analysis["gaps"] == []
    assert analysis["requests"][0]["tool_choice"] == "auto"
    assert analysis["requests"][0]["parallel_tool_calls"] is True
    assert analysis["requests"][0]["include"] == ["reasoning.encrypted_content"]
