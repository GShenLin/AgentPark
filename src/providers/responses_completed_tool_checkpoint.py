from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from src.providers.responses_completed_tool_receipt import CHECKPOINT_PREFIX
from src.providers.responses_completed_tool_receipt import CHECKPOINT_SCHEMA_VERSION
from src.providers.responses_completed_tool_receipt import (
    CompletedToolReceiptContractError,
)
from src.providers.responses_completed_tool_receipt import build_receipt_item
from src.providers.responses_completed_tool_receipt import completed_exchange_manifests
from src.providers.responses_completed_tool_receipt import is_checkpoint_receipt
from src.providers.responses_completed_tool_receipt import serialized_chars
from src.providers.responses_completed_tool_receipt import task_direction_snapshot
from src.providers.responses_completed_tool_receipt import tool_exchange_indexes
from src.tool.tool_call_protocol import ToolCallEnvelope
from src.workspace_checkpoint_policy import CHECKPOINT_RETAIN
from src.workspace_checkpoint_policy import CHECKPOINT_RETIRE_VERIFIED
from src.workspace_checkpoint_policy import checkpoint_policy_from_tool_arguments


class CompletedToolCheckpointContractError(RuntimeError):
    """Raised when an eligible checkpoint cannot produce a valid replacement."""


@dataclass(frozen=True)
class CheckpointTrigger:
    call: ToolCallEnvelope
    kind: str
    context_checkpoint_policy: str | None = None


@dataclass(frozen=True)
class CompletedToolCheckpointResult:
    items: tuple[Any, ...]
    checkpoint_call_id: str
    checkpoint_kind: str
    context_checkpoint_policy: str
    task_direction_revision: int
    newly_retired_exchange_count: int
    retired_exchange_count: int
    receipt_count: int
    before_chars: int
    after_chars: int

    def to_notice_payload(self) -> dict[str, Any]:
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_call_id": self.checkpoint_call_id,
            "checkpoint_kind": self.checkpoint_kind,
            "context_checkpoint_policy": self.context_checkpoint_policy,
            "task_direction_revision": self.task_direction_revision,
            "newly_retired_exchange_count": self.newly_retired_exchange_count,
            "retired_exchange_count": self.retired_exchange_count,
            "receipt_count": self.receipt_count,
            "before_chars": self.before_chars,
            "after_chars": self.after_chars,
            "saved_chars": max(0, self.before_chars - self.after_chars),
        }


class CompletedToolContextCheckpoint:
    """Retire completed tool exchanges at an explicit workspace handoff."""

    def __init__(self, *, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("completed tool checkpoint enabled must be a boolean")
        self._enabled = enabled
        self._retired_exchanges: dict[str, dict[str, Any]] = {}
        self._receipt_items: list[dict[str, Any]] = []
        self._last_task_direction_revision: int | None = None
        self._verified_retirement_policy = CHECKPOINT_RETAIN

    def apply(self, items: object) -> list[Any]:
        source = list(items) if isinstance(items, list) else []
        if not self._enabled or not self._retired_exchanges:
            return source

        retired_ids = set(self._retired_exchanges)
        calls, outputs = tool_exchange_indexes(source, retired_ids)
        partial = sorted((set(calls) ^ set(outputs)) & retired_ids)
        if partial:
            raise CompletedToolCheckpointContractError(
                "retired tool context contains incomplete function-call exchanges: "
                + ", ".join(partial)
            )

        remove_indexes = {
            *[index for indexes in calls.values() for index in indexes],
            *[index for indexes in outputs.values() for index in indexes],
        }
        receipt_indexes = {
            index
            for index, item in enumerate(source)
            if is_checkpoint_receipt(item)
        }
        insertion_candidates = remove_indexes | receipt_indexes
        insertion_index = min(insertion_candidates) if insertion_candidates else len(source)
        retained = [
            item
            for index, item in enumerate(source)
            if index not in remove_indexes and index not in receipt_indexes
        ]
        if not self._receipt_items:
            raise CompletedToolCheckpointContractError(
                "retired tool context is missing checkpoint receipts"
            )
        insert_at = min(insertion_index, len(retained))
        retained[insert_at:insert_at] = [
            dict(receipt) for receipt in self._receipt_items
        ]
        return retained

    def maybe_checkpoint(
        self,
        *,
        items: object,
        function_calls: object,
        executions: object,
        task_direction_loader: Callable[[], object],
    ) -> CompletedToolCheckpointResult | None:
        if not self._enabled:
            return None
        trigger = _successful_checkpoint_trigger(
            function_calls,
            executions,
            allow_pytest_verified=(
                bool(self._receipt_items)
                and self._verified_retirement_policy == CHECKPOINT_RETIRE_VERIFIED
            ),
            allow_analysis_verification=bool(self._receipt_items),
        )
        if trigger is None:
            return None

        source = list(items) if isinstance(items, list) else []
        try:
            manifests = completed_exchange_manifests(source)
        except CompletedToolReceiptContractError as exc:
            raise CompletedToolCheckpointContractError(str(exc)) from exc
        if not manifests:
            return None

        try:
            snapshot = task_direction_snapshot(task_direction_loader())
        except CompletedToolReceiptContractError as exc:
            raise CompletedToolCheckpointContractError(str(exc)) from exc
        new_manifests = [
            manifest
            for manifest in manifests
            if manifest["call_id"] not in self._retired_exchanges
        ]
        if not new_manifests:
            return None
        for manifest in manifests:
            self._retired_exchanges[manifest["call_id"]] = manifest
        revision = int(snapshot["revision"])
        self._receipt_items.append(build_receipt_item(
            checkpoint_call=trigger.call,
            checkpoint_kind=trigger.kind,
            context_checkpoint_policy=trigger.context_checkpoint_policy,
            task_direction=snapshot,
            include_task_direction_snapshot=(
                self._last_task_direction_revision != revision
            ),
            retired_exchanges=new_manifests,
        ))
        if (
            trigger.kind == "workspace_handoff"
            and trigger.context_checkpoint_policy is not None
        ):
            self._verified_retirement_policy = trigger.context_checkpoint_policy
        self._last_task_direction_revision = revision

        before_chars = serialized_chars(source)
        rewritten = self.apply(source)
        return CompletedToolCheckpointResult(
            items=tuple(rewritten),
            checkpoint_call_id=trigger.call.call_id,
            checkpoint_kind=trigger.kind,
            context_checkpoint_policy=self._verified_retirement_policy,
            task_direction_revision=revision,
            newly_retired_exchange_count=len(new_manifests),
            retired_exchange_count=len(self._retired_exchanges),
            receipt_count=len(self._receipt_items),
            before_chars=before_chars,
            after_chars=serialized_chars(rewritten),
        )


def completed_tool_checkpoint_enabled(runtime: object) -> bool:
    config = getattr(runtime, "config", None)
    value = (
        config.get("responsesCompletedToolCheckpointEnabled", False)
        if isinstance(config, dict)
        else False
    )
    if not isinstance(value, bool):
        raise ValueError(
            "provider.responsesCompletedToolCheckpointEnabled must be a boolean."
        )
    return value


def load_task_direction_snapshot(runtime: object) -> dict[str, Any]:
    from src.task_direction_store import TaskDirectionStore

    stored = TaskDirectionStore.for_agent(runtime).read()
    if stored is None:
        raise CompletedToolCheckpointContractError(
            "eligible completed-tool checkpoint requires an initialized task direction"
        )
    return stored.to_payload()


def _successful_checkpoint_trigger(
    function_calls: object,
    executions: object,
    *,
    allow_pytest_verified: bool,
    allow_analysis_verification: bool,
) -> CheckpointTrigger | None:
    execution_by_call_id = {
        str(getattr(execution, "call_id", "") or "").strip(): execution
        for execution in executions if isinstance(executions, list)
        if str(getattr(execution, "call_id", "") or "").strip()
    }
    candidates: list[CheckpointTrigger] = []
    for call in function_calls if isinstance(function_calls, list) else []:
        if not isinstance(call, ToolCallEnvelope):
            continue
        execution = execution_by_call_id.get(call.call_id)
        if execution is None or not _execution_succeeded(execution):
            continue
        if call.name == "workspace_exec":
            policy = checkpoint_policy_from_tool_arguments(call.arguments)
            if policy is not None:
                candidates.append(
                    CheckpointTrigger(
                        call=call,
                        kind="workspace_handoff",
                        context_checkpoint_policy=policy,
                    )
                )
            continue
        if (
            allow_pytest_verified
            and call.name == "execute_console_command"
            and _is_verified_pytest_execution(execution)
        ):
            candidates.append(CheckpointTrigger(call=call, kind="pytest_verified"))
            continue
        if (
            allow_analysis_verification
            and call.name == "run_analysis_verification"
            and _is_analysis_verification_execution(execution)
        ):
            candidates.append(CheckpointTrigger(call=call, kind="analysis_verification"))
    return candidates[-1] if candidates else None


def _execution_succeeded(execution: object) -> bool:
    status = str(getattr(execution, "status", "") or "completed").strip().lower()
    error = str(getattr(execution, "error", "") or "").strip()
    return status in {"", "ok", "done", "success", "completed"} and not error


def _is_verified_pytest_execution(execution: object) -> bool:
    payload = _execution_payload(execution)
    completion = payload.get("detected_completion")
    if not isinstance(completion, dict):
        return False
    failed_tests = completion.get("failed_tests")
    return (
        str(payload.get("status") or "").strip().lower() == "success"
        and payload.get("returncode") == 0
        and not isinstance(payload.get("returncode"), bool)
        and str(completion.get("kind") or "").strip().lower() == "pytest"
        and completion.get("completed") is True
        and failed_tests == 0
        and not isinstance(failed_tests, bool)
    )


def _is_analysis_verification_execution(execution: object) -> bool:
    payload = _execution_payload(execution)
    return (
        str(payload.get("status") or "").strip().lower() == "success"
        and bool(str(payload.get("run_id") or "").strip())
        and isinstance(payload.get("gates"), list)
        and bool(payload["gates"])
    )


def _execution_payload(execution: object) -> dict[str, Any]:
    value = getattr(execution, "cleaned_result", None)
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "CHECKPOINT_PREFIX",
    "CompletedToolCheckpointContractError",
    "CompletedToolCheckpointResult",
    "CompletedToolContextCheckpoint",
    "completed_tool_checkpoint_enabled",
    "load_task_direction_snapshot",
]
