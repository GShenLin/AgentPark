from __future__ import annotations

import json

import pytest

from src.providers.responses_completed_tool_checkpoint import CHECKPOINT_PREFIX
from src.providers.responses_completed_tool_checkpoint import (
    CompletedToolContextCheckpoint,
)
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


def _workspace_checkpoint_call(
    call_id: str = "handoff",
    *,
    policy: str = "retire_after_verified",
) -> ToolCallEnvelope:
    return _call(
        call_id,
        "workspace_exec",
        {
            "context_checkpoint": policy,
            "stages": [
                {
                    "id": "handoff",
                    "operations": [{"kind": "update_task_direction"}],
                },
                {
                    "id": "patch",
                    "operations": [{"kind": "apply_patch"}],
                },
            ]
        },
    )


def _pytest_call(call_id: str = "pytest") -> ToolCallEnvelope:
    return _call(
        call_id,
        "execute_console_command",
        {
            "command": "python -m pytest -q tests/test_contracts.py",
            "timeout_seconds": 120,
            "progress_timeout_seconds": 30,
        },
    )


def _pytest_execution(
    call_id: str = "pytest",
    *,
    failed_tests: int = 0,
    status: str = "completed",
    error: str | None = None,
) -> ToolCallExecution:
    return _execution(
        call_id,
        "execute_console_command",
        status=status,
        error=error,
        result=json.dumps(
            {
                "status": "success" if failed_tests == 0 else "error",
                "returncode": 0 if failed_tests == 0 else 1,
                "detected_completion": {
                    "kind": "pytest",
                    "completed": True,
                    "failed_tests": failed_tests,
                },
            }
        ),
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
            "evidence": [],
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


def _last_receipt_payload(items: list[object]) -> dict:
    texts = [
        part.get("text")
        for item in items
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content") or []
        if isinstance(part, dict)
        and str(part.get("text") or "").startswith(CHECKPOINT_PREFIX)
    ]
    assert texts
    return json.loads(str(texts[-1]).split("\n", 1)[1])


def _installed_checkpoint() -> tuple[CompletedToolContextCheckpoint, object]:
    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    result = checkpoint.maybe_checkpoint(
        items=_exchange("read-1", "read_file", "{}", "source"),
        function_calls=[_workspace_checkpoint_call()],
        executions=[_execution("handoff", "workspace_exec")],
        task_direction_loader=_snapshot,
    )
    assert result is not None
    return checkpoint, result


def test_verified_pytest_rolls_context_only_after_installed_handoff():
    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    assert checkpoint.maybe_checkpoint(
        items=_exchange("read-1", "read_file", "{}", "source"),
        function_calls=[_pytest_call()],
        executions=[_pytest_execution()],
        task_direction_loader=lambda: pytest.fail("loader must not run"),
    ) is None

    checkpoint, first = _installed_checkpoint()
    first_receipt = first.items[0]
    history = [
        *first.items,
        *_exchange("handoff", "workspace_exec", '{"patch":"large"}', "success"),
    ]
    rolled = checkpoint.maybe_checkpoint(
        items=history,
        function_calls=[_pytest_call()],
        executions=[_pytest_execution()],
        task_direction_loader=_snapshot,
    )

    assert rolled is not None
    assert rolled.checkpoint_kind == "pytest_verified"
    assert rolled.newly_retired_exchange_count == 1
    assert rolled.retired_exchange_count == 2
    assert rolled.receipt_count == 2
    assert rolled.items[0] == first_receipt
    payload = _last_receipt_payload(list(rolled.items))
    assert payload["checkpoint"]["kind"] == "pytest_verified"
    assert payload["task_direction"] == {"mode": "unchanged", "revision": 2}
    assert [
        item["call_id"] for item in payload["newly_retired_exchanges"]
    ] == ["handoff"]


def test_intermediate_handoff_retains_mutation_until_terminal_handoff():
    checkpoint = CompletedToolContextCheckpoint(enabled=True)
    stage1 = checkpoint.maybe_checkpoint(
        items=_exchange("read-1", "read_file", "{}", "source"),
        function_calls=[
            _workspace_checkpoint_call(
                "stage1",
                policy="retain_until_next_handoff",
            )
        ],
        executions=[_execution("stage1", "workspace_exec")],
        task_direction_loader=lambda: _snapshot(2),
    )
    assert stage1 is not None
    stage1_history = [
        *stage1.items,
        *_exchange("stage1", "workspace_exec", '{"patch":"stage1"}', "success"),
    ]

    assert checkpoint.maybe_checkpoint(
        items=stage1_history,
        function_calls=[_pytest_call("stage1-test")],
        executions=[_pytest_execution("stage1-test")],
        task_direction_loader=lambda: pytest.fail("loader must not run"),
    ) is None
    assert checkpoint.apply(stage1_history) == stage1_history

    stage2 = checkpoint.maybe_checkpoint(
        items=[
            *stage1_history,
            *_exchange("stage1-test", "execute_console_command", "{}", "passed"),
        ],
        function_calls=[
            _workspace_checkpoint_call(
                "stage2",
                policy="retire_after_verified",
            )
        ],
        executions=[_execution("stage2", "workspace_exec")],
        task_direction_loader=lambda: _snapshot(3),
    )
    assert stage2 is not None
    assert stage2.context_checkpoint_policy == "retire_after_verified"
    stage2_history = [
        *stage2.items,
        *_exchange("stage2", "workspace_exec", '{"patch":"stage2"}', "success"),
    ]

    verified = checkpoint.maybe_checkpoint(
        items=stage2_history,
        function_calls=[_pytest_call("stage2-test")],
        executions=[_pytest_execution("stage2-test")],
        task_direction_loader=lambda: _snapshot(3),
    )
    assert verified is not None
    assert verified.checkpoint_kind == "pytest_verified"


@pytest.mark.parametrize(
    "execution",
    [
        _pytest_execution(
            failed_tests=1,
            status="error",
            error="Pytest reported 1 failed/error tests.",
        ),
        _execution(
            "pytest",
            "execute_console_command",
            result='{"status":"success","returncode":0}',
        ),
        _execution(
            "pytest",
            "execute_console_command",
            result=(
                '{"status":"success","returncode":0,'
                '"detected_completion":{"kind":"pytest","completed":true,'
                '"failed_tests":true}}'
            ),
        ),
    ],
)
def test_failed_or_unproven_pytest_preserves_full_mutation_context(execution):
    checkpoint, first = _installed_checkpoint()
    history = [
        *first.items,
        *_exchange("handoff", "workspace_exec", '{"patch":"large"}', "success"),
    ]

    assert checkpoint.maybe_checkpoint(
        items=history,
        function_calls=[_pytest_call()],
        executions=[execution],
        task_direction_loader=lambda: pytest.fail("loader must not run"),
    ) is None
    assert checkpoint.apply(history) == history


def test_direct_patch_success_does_not_roll_failed_diagnostic_context():
    checkpoint, first = _installed_checkpoint()
    history = [
        *first.items,
        *_exchange("handoff", "workspace_exec", '{"patch":"large"}', "success"),
        *_exchange(
            "failed-test",
            "execute_console_command",
            '{"command":"pytest"}',
            "1 failed",
        ),
    ]
    direct_patch = _call("repair", "apply_patch", {"patch": "repair"})

    assert checkpoint.maybe_checkpoint(
        items=history,
        function_calls=[direct_patch],
        executions=[_execution("repair", "apply_patch")],
        task_direction_loader=lambda: pytest.fail("loader must not run"),
    ) is None
    assert checkpoint.apply(history) == history


def test_structured_analysis_verification_rolls_prior_verified_history():
    checkpoint, first = _installed_checkpoint()
    history = [
        *first.items,
        *_exchange("focused", "execute_console_command", "{}", "110 passed"),
    ]
    call = _call("verification", "run_analysis_verification", {"gates": {}})
    execution = _execution(
        "verification",
        "run_analysis_verification",
        result=json.dumps(
            {
                "status": "success",
                "run_id": "verification_123",
                "gates": [{"name": "security", "status": "passed"}],
            }
        ),
    )

    rolled = checkpoint.maybe_checkpoint(
        items=history,
        function_calls=[call],
        executions=[execution],
        task_direction_loader=_snapshot,
    )
    assert rolled is not None
    assert rolled.checkpoint_kind == "analysis_verification"
    assert _last_receipt_payload(list(rolled.items))["checkpoint"]["kind"] == (
        "analysis_verification"
    )
