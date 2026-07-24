from __future__ import annotations

import json

import pytest

from src.providers.responses_completed_tool_checkpoint import CHECKPOINT_PREFIX
from src.providers.responses_completed_tool_checkpoint import (
    CompletedToolCheckpointContractError,
)
from src.providers.responses_completed_tool_checkpoint import (
    CompletedToolContextCheckpoint,
)
from src.providers.responses_completed_tool_checkpoint import (
    completed_tool_checkpoint_enabled,
)
from src.providers.responses_runtime_support import checkpoint_completed_tool_context
from src.responses_provider_config import validate_responses_provider_config
from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool.tool_call_protocol import ToolCallExecution


def _call(call_id: str, name: str, arguments: dict) -> ToolCallEnvelope:
    arguments_json = json.dumps(arguments, ensure_ascii=False)
    return ToolCallEnvelope(
        name=name,
        call_id=call_id,
        arguments=arguments,
        arguments_json=arguments_json,
        provider="openai_responses",
    )


def _execution(
    call_id: str,
    name: str,
    *,
    status: str = "completed",
    error: str | None = None,
    result: str = '{"status":"success"}',
) -> ToolCallExecution:
    return ToolCallExecution(
        func_name=name,
        call_id=call_id,
        cleaned_result=result,
        status=status,
        error=error,
    )


def _workspace_checkpoint_call(call_id: str = "checkpoint") -> ToolCallEnvelope:
    return _call(
        call_id,
        "workspace_exec",
        {
            "context_checkpoint": "retain_until_next_handoff",
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
        },
    )


def _snapshot(revision: int = 2) -> dict:
    return {
        "task_id": "task-1",
        "status": "active",
        "revision": revision,
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


def _exchange(call_id: str, name: str, arguments: str, output: str) -> list[dict]:
    return [
        {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
            "status": "completed",
        },
    ]


def _receipt_payloads(items: list[object]) -> list[dict]:
    messages = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "message"
        and item.get("role") == "developer"
    ]
    payloads = []
    for message in messages:
        text = message["content"][0]["text"]
        assert text.startswith(CHECKPOINT_PREFIX + "\n")
        payloads.append(json.loads(text.split("\n", 1)[1]))
    return payloads


def _receipt_payload(items: list[object]) -> dict:
    payloads = _receipt_payloads(items)
    assert payloads
    return payloads[-1]


def test_checkpoint_retires_complete_exchanges_and_preserves_authoritative_snapshot():
    large_output = "x" * 20_000
    items = [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "task"}]},
        *_exchange("read-1", "workspace_exec", '{"stages":[]}', large_output),
        *_exchange("direction-1", "replace_task_direction", '{"state":{}}', '{"status":"success"}'),
    ]
    checkpoint = CompletedToolContextCheckpoint(enabled=True)

    result = checkpoint.maybe_checkpoint(
        items=items,
        function_calls=[_workspace_checkpoint_call()],
        executions=[_execution("checkpoint", "workspace_exec")],
        task_direction_loader=lambda: _snapshot(),
    )

    assert result is not None
    assert result.retired_exchange_count == 2
    assert result.before_chars > result.after_chars
    assert result.to_notice_payload()["saved_chars"] > 18_000
    assert not any(
        isinstance(item, dict)
        and item.get("type") in {"function_call", "function_call_output"}
        for item in result.items
    )
    payload = _receipt_payload(list(result.items))
    assert payload["schema_version"] == 2
    assert payload["checkpoint"]["call_id"] == "checkpoint"
    assert payload["checkpoint"]["kind"] == "workspace_handoff"
    assert payload["task_direction"] == {
        "mode": "snapshot",
        "value": _snapshot(),
    }
    assert [item["call_id"] for item in payload["newly_retired_exchanges"]] == [
        "read-1",
        "direction-1",
    ]
    assert all(
        len(item["arguments_sha256"]) == 64
        for item in payload["newly_retired_exchanges"]
    )


def test_checkpoint_apply_is_idempotent_and_compacts_rebuilt_history():
    original = [
        {"type": "message", "role": "user", "content": []},
        *_exchange("read-1", "read_file", '{"file_path":"a.py"}', "source"),
    ]
    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    first = checkpoint.maybe_checkpoint(
        items=original,
        function_calls=[_workspace_checkpoint_call()],
        executions=[_execution("checkpoint", "workspace_exec")],
        task_direction_loader=lambda: _snapshot(),
    )
    assert first is not None

    assert checkpoint.apply(list(first.items)) == list(first.items)
    rebuilt = checkpoint.apply(original)
    assert rebuilt == list(first.items)


def test_second_checkpoint_appends_receipt_and_preserves_stable_prefix():
    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    first = checkpoint.maybe_checkpoint(
        items=_exchange("read-1", "read_file", "{}", "source"),
        function_calls=[_workspace_checkpoint_call("checkpoint-1")],
        executions=[_execution("checkpoint-1", "workspace_exec")],
        task_direction_loader=lambda: _snapshot(2),
    )
    assert first is not None
    first_receipt = first.items[0]
    with_new_exchange = [
        *first.items,
        *_exchange("test-1", "execute_console_command", '{"command":"pytest"}', "1 passed"),
    ]

    second = checkpoint.maybe_checkpoint(
        items=with_new_exchange,
        function_calls=[_workspace_checkpoint_call("checkpoint-2")],
        executions=[_execution("checkpoint-2", "workspace_exec")],
        task_direction_loader=lambda: _snapshot(3),
    )

    assert second is not None
    assert second.retired_exchange_count == 2
    assert second.newly_retired_exchange_count == 1
    assert second.receipt_count == 2
    assert second.items[0] == first_receipt
    payloads = _receipt_payloads(list(second.items))
    assert len(payloads) == 2
    payload = _receipt_payload(list(second.items))
    assert payload["checkpoint"]["call_id"] == "checkpoint-2"
    assert payload["task_direction"]["value"]["revision"] == 3
    assert {
        item["call_id"] for item in payload["newly_retired_exchanges"]
    } == {"test-1"}


@pytest.mark.parametrize(
    ("call", "execution"),
    [
        (
            _call(
                "same-stage",
                "workspace_exec",
                {
                    "stages": [
                        {
                            "id": "invalid",
                            "operations": [
                                {"kind": "update_task_direction"},
                                {"kind": "apply_patch"},
                            ],
                        }
                    ]
                },
            ),
            _execution("same-stage", "workspace_exec"),
        ),
        (
            _workspace_checkpoint_call("failed"),
            _execution("failed", "workspace_exec", status="error", error="patch failed"),
        ),
        (
            _call("direct", "apply_patch", {"patch": "*** Begin Patch"}),
            _execution("direct", "apply_patch"),
        ),
    ],
)
def test_checkpoint_requires_successful_ordered_workspace_handoff(call, execution):
    loader_called = False

    def load():
        nonlocal loader_called
        loader_called = True
        return _snapshot()

    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    assert checkpoint.maybe_checkpoint(
        items=_exchange("read-1", "read_file", "{}", "source"),
        function_calls=[call],
        executions=[execution],
        task_direction_loader=load,
    ) is None
    assert loader_called is False


def test_disabled_checkpoint_does_not_load_direction_or_change_items():
    items = _exchange("read-1", "read_file", "{}", "source")
    checkpoint = CompletedToolContextCheckpoint(enabled=False)

    assert checkpoint.apply(items) == items
    assert checkpoint.maybe_checkpoint(
        items=items,
        function_calls=[_workspace_checkpoint_call()],
        executions=[_execution("checkpoint", "workspace_exec")],
        task_direction_loader=lambda: pytest.fail("loader must not run"),
    ) is None


def test_checkpoint_rejects_incomplete_retired_exchange_on_rebuild():
    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    result = checkpoint.maybe_checkpoint(
        items=_exchange("read-1", "read_file", "{}", "source"),
        function_calls=[_workspace_checkpoint_call()],
        executions=[_execution("checkpoint", "workspace_exec")],
        task_direction_loader=lambda: _snapshot(),
    )
    assert result is not None

    with pytest.raises(CompletedToolCheckpointContractError, match="incomplete"):
        checkpoint.apply(
            [
                {
                    "type": "function_call",
                    "call_id": "read-1",
                    "name": "read_file",
                    "arguments": "{}",
                }
            ]
        )


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        {},
        {"revision": True, "state": {}},
        {"revision": 2, "state": "not-an-object"},
    ],
)
def test_checkpoint_rejects_invalid_task_direction_snapshot(snapshot):
    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    with pytest.raises(CompletedToolCheckpointContractError):
        checkpoint.maybe_checkpoint(
            items=_exchange("read-1", "read_file", "{}", "source"),
            function_calls=[_workspace_checkpoint_call()],
            executions=[_execution("checkpoint", "workspace_exec")],
            task_direction_loader=lambda: snapshot,
        )


def test_checkpoint_helper_emits_structured_runtime_notice(monkeypatch):
    notices = []
    monkeypatch.setattr(
        "src.providers.responses_completed_tool_checkpoint.load_task_direction_snapshot",
        lambda _runtime: _snapshot(),
    )

    class Runtime:
        def _emit_responses_notice(self, *, stage, payload):
            notices.append((stage, payload))

    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    items = checkpoint_completed_tool_context(
        Runtime(),
        checkpoint,
        items=_exchange("read-1", "read_file", "{}", "source" * 1_000),
        function_calls=[_workspace_checkpoint_call()],
        executions=[_execution("checkpoint", "workspace_exec")],
    )
    assert items is not None
    assert notices[0][0] == "openai_responses_completed_tool_checkpoint"
    assert notices[0][1]["retired_exchange_count"] == 1
    assert notices[0][1]["saved_chars"] > 0


@pytest.mark.parametrize("value", ["true", 1, [], {}])
def test_checkpoint_config_rejects_non_boolean_values(value):
    provider = {
        "responsesApi": True,
        "toolResultSubmissionMaxChars": 50_000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 0,
        "toolContextCompactionInputTokens": 0,
        "toolContextCompactionCurrentInputTokens": 0,
        "toolContextCompactionOutputTokens": 0,
        "responsesReplayReasoningItems": False,
        "responsesCompletedToolCheckpointEnabled": value,
    }
    with pytest.raises(ValueError, match="responsesCompletedToolCheckpointEnabled"):
        validate_responses_provider_config("openai", provider, "openai")


def test_checkpoint_runtime_flag_defaults_false_and_accepts_boolean():
    class Runtime:
        config = {}

    assert completed_tool_checkpoint_enabled(Runtime()) is False
    Runtime.config = {"responsesCompletedToolCheckpointEnabled": True}
    assert completed_tool_checkpoint_enabled(Runtime()) is True
