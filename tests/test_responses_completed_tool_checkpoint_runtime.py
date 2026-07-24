from __future__ import annotations

import json

from src.providers.openai_responses_stream_normalizer import (
    OpenAIResponsesStreamEventNormalizer,
)
from src.providers.responses_completed_tool_checkpoint import CHECKPOINT_PREFIX
from src.tool.base_tool import BaseTool


def _task_direction_snapshot() -> dict:
    return {
        "task_id": "task-1",
        "status": "active",
        "revision": 2,
        "updated_at": "2026-07-24T00:00:00+08:00",
        "state": {
            "objective": "Keep the exact task objective.",
            "plan": ["inspect", "implement", "verify"],
            "evidence": [{"id": "E1", "summary": "Source inspected."}],
            "hypotheses": [],
            "risks": [],
            "criteria": [],
        },
    }


def _checkpoint_arguments() -> dict:
    return {
        "context_checkpoint": "retire_after_verified",
        "stages": [
            {
                "id": "handoff",
                "operations": [
                    {
                        "id": "direction",
                        "kind": "update_task_direction",
                        "arguments": {},
                    }
                ],
            },
            {
                "id": "mutation",
                "operations": [
                    {
                        "id": "patch",
                        "kind": "apply_patch",
                        "arguments": {},
                    }
                ],
            },
        ]
    }


def test_item_level_runtime_retires_prior_exchange_after_workspace_checkpoint(
    monkeypatch,
):
    from src.providers.openai_agent import OpenAIAgent

    monkeypatch.setattr(
        "src.providers.responses_completed_tool_checkpoint.load_task_direction_snapshot",
        lambda _runtime: _task_direction_snapshot(),
    )
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesApi": True,
        "responsesReplayReasoningItems": False,
        "responsesCompletedToolCheckpointEnabled": True,
        "toolResultSubmissionMaxChars": 50_000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    agent.tools.function_map["read_file"] = lambda file_path: "source" * 2_000
    agent.tools.function_map["workspace_exec"] = lambda stages, context_checkpoint: {
        "status": "success",
        "stages": len(stages),
        "context_checkpoint": context_checkpoint,
    }
    agent.tools.function_map["execute_console_command"] = (
        lambda command, timeout_seconds, progress_timeout_seconds: {
            "status": "success",
            "returncode": 0,
            "detected_completion": {
                "kind": "pytest",
                "completed": True,
                "failed_tests": 0,
            },
        }
    )
    events = []
    agent.tool_event_callback = events.append
    payloads = []

    def emit(handler, item):
        normalizer = OpenAIResponsesStreamEventNormalizer()
        raw = {"type": "response.output_item.done", "item": item}
        for event in normalizer.ingest_event(raw):
            handler(event)

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        request_index = len(payloads)
        if request_index == 1:
            item = {
                "type": "function_call",
                "id": "fc-read",
                "call_id": "call-read",
                "name": "read_file",
                "arguments": '{"file_path":"large.py"}',
            }
            emit(kwargs["item_event_handler"], item)
            return {"id": "resp-read", "output": [item]}
        if request_index == 2:
            item = {
                "type": "function_call",
                "id": "fc-checkpoint",
                "call_id": "call-checkpoint",
                "name": "workspace_exec",
                "arguments": json.dumps(_checkpoint_arguments()),
            }
            emit(kwargs["item_event_handler"], item)
            return {"id": "resp-checkpoint", "output": [item]}
        if request_index == 3:
            item = {
                "type": "function_call",
                "id": "fc-pytest",
                "call_id": "call-pytest",
                "name": "execute_console_command",
                "arguments": json.dumps(
                    {
                        "command": "python -m pytest -q",
                        "timeout_seconds": 120,
                        "progress_timeout_seconds": 30,
                    }
                ),
            }
            emit(kwargs["item_event_handler"], item)
            return {"id": "resp-pytest", "output": [item]}
        return {
            "id": "resp-final",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
        }

    agent._stream_responses_with_retry = fake_stream
    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "perform the task"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    ) == "done"

    second_ids = {
        item.get("call_id")
        for item in payloads[1]["input"]
        if isinstance(item, dict)
    }
    assert "call-read" in second_ids
    third_ids = {
        item.get("call_id")
        for item in payloads[2]["input"]
        if isinstance(item, dict)
    }
    assert "call-read" not in third_ids
    assert "call-checkpoint" in third_ids
    fourth_ids = {
        item.get("call_id")
        for item in payloads[3]["input"]
        if isinstance(item, dict)
    }
    assert "call-read" not in fourth_ids
    assert "call-checkpoint" not in fourth_ids
    assert "call-pytest" in fourth_ids
    checkpoint_messages = [
        item
        for item in payloads[2]["input"]
        if isinstance(item, dict)
        and item.get("type") == "message"
        and any(
            isinstance(part, dict)
            and str(part.get("text") or "").startswith(CHECKPOINT_PREFIX)
            for part in item.get("content") or []
        )
    ]
    assert len(checkpoint_messages) == 1
    fourth_checkpoint_messages = [
        item
        for item in payloads[3]["input"]
        if isinstance(item, dict)
        and item.get("type") == "message"
        and any(
            isinstance(part, dict)
            and str(part.get("text") or "").startswith(CHECKPOINT_PREFIX)
            for part in item.get("content") or []
        )
    ]
    assert len(fourth_checkpoint_messages) == 2
    assert fourth_checkpoint_messages[0] == checkpoint_messages[0]
    notices = [
        json.loads(event["message"])
        for event in events
        if event.get("type") == "runtime_notice"
        and event.get("stage") == "openai_responses_completed_tool_checkpoint"
    ]
    assert [notice["checkpoint_kind"] for notice in notices] == [
        "workspace_handoff",
        "pytest_verified",
    ]
    assert notices[0]["retired_exchange_count"] == 1
    assert notices[0]["saved_chars"] > 10_000
    assert notices[1]["newly_retired_exchange_count"] == 1
    assert notices[1]["receipt_count"] == 2
