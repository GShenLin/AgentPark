from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
import json
from typing import Any, Callable

from functions.agent_patch_tools import apply_patch
from functions.console_tools import execute_console_command
from functions.file_read_tools import read_file
from functions.rg_tools import rg_list_files
from functions.rg_tools import rg_search_text
from src.runtime_cancellation import cancel_source_from_agent
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.task_direction_tools import update_task_direction


MAX_STAGES = 12
MAX_OPERATIONS_PER_STAGE = 8
MAX_TOTAL_OPERATIONS = 48
MAX_RESULT_CHARS = 240_000
MAX_REFERENCE_PATH_SEGMENTS = 16


class WorkspaceExecutionContractError(ValueError):
    """Raised when a workspace execution program violates its public contract."""


@dataclass(frozen=True)
class WorkspaceOperation:
    operation_id: str
    kind: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class WorkspaceStage:
    stage_id: str
    operations: tuple[WorkspaceOperation, ...]


_OPERATION_ARGUMENTS: dict[str, frozenset[str]] = {
    "read_file": frozenset({"file_path", "start_line", "end_line"}),
    "search_text": frozenset(
        {
            "query",
            "project_root",
            "include_globs",
            "exclude_globs",
            "case_sensitive",
            "fixed_strings",
            "max_results",
        }
    ),
    "list_files": frozenset(
        {"project_root", "include_globs", "exclude_globs", "max_results"}
    ),
    "run_command": frozenset({"command", "timeout_seconds"}),
    "apply_patch": frozenset({"patch", "encoding", "return_mode", "required_changes"}),
    "update_task_direction": frozenset(
        {"expected_revision", "evidence", "hypotheses", "risks", "criteria"}
    ),
}

_REQUIRED_ARGUMENTS: dict[str, frozenset[str]] = {
    "read_file": frozenset({"file_path"}),
    "search_text": frozenset({"query"}),
    "list_files": frozenset(),
    "run_command": frozenset({"command"}),
    "apply_patch": frozenset({"patch", "required_changes"}),
    "update_task_direction": frozenset(
        {"expected_revision", "evidence", "hypotheses", "risks", "criteria"}
    ),
}
_MUTATING_OPERATION_KINDS = frozenset({"apply_patch", "update_task_direction"})


def execute_workspace_program(stages: object, *, agent: object) -> dict[str, Any]:
    program = _parse_program(stages)
    cancel_source = cancel_source_from_agent(agent)
    stage_results: list[dict[str, Any]] = []
    completed_operations: dict[str, dict[str, Any]] = {}
    total_result_chars = 0

    for stage in program:
        raise_if_cancel_requested(cancel_source)
        with ThreadPoolExecutor(
            max_workers=len(stage.operations),
            thread_name_prefix=f"workspace-exec-{stage.stage_id}",
        ) as executor:
            resolved_operations = [
                WorkspaceOperation(
                    operation_id=operation.operation_id,
                    kind=operation.kind,
                    arguments=_resolve_references(operation.arguments, completed_operations),
                )
                for operation in stage.operations
            ]
            futures = []
            for operation in resolved_operations:
                context = copy_context()
                futures.append(executor.submit(context.run, _execute_operation, operation, agent))
            operation_results = [future.result() for future in futures]
        completed_operations.update(
            {str(result["id"]): result for result in operation_results}
        )

        encoded_results = json.dumps(operation_results, ensure_ascii=False)
        total_result_chars += len(encoded_results)
        if total_result_chars > MAX_RESULT_CHARS:
            raise WorkspaceExecutionContractError(
                f"workspace_exec result exceeds the {MAX_RESULT_CHARS} character contract limit"
            )
        stage_results.append(
            {
                "stage_id": stage.stage_id,
                "status": _aggregate_status(operation_results),
                "operations": operation_results,
            }
        )
        if stage_results[-1]["status"] == "error":
            break

    return {
        "status": _aggregate_status(stage_results),
        "stage_count": len(stage_results),
        "operation_count": sum(len(stage["operations"]) for stage in stage_results),
        "stages": stage_results,
    }


def _parse_program(raw_stages: object) -> tuple[WorkspaceStage, ...]:
    if not isinstance(raw_stages, list) or not raw_stages:
        raise WorkspaceExecutionContractError("stages must be a non-empty array")
    if len(raw_stages) > MAX_STAGES:
        raise WorkspaceExecutionContractError(f"stages cannot contain more than {MAX_STAGES} items")

    stages: list[WorkspaceStage] = []
    seen_stage_ids: set[str] = set()
    seen_operation_ids: set[str] = set()
    completed_operation_ids: set[str] = set()
    operation_count = 0
    for stage_index, raw_stage in enumerate(raw_stages):
        if not isinstance(raw_stage, dict):
            raise WorkspaceExecutionContractError(f"stages[{stage_index}] must be an object")
        _reject_unknown_keys(raw_stage, {"id", "operations"}, f"stages[{stage_index}]")
        stage_id = _required_identifier(raw_stage.get("id"), f"stages[{stage_index}].id")
        if stage_id in seen_stage_ids:
            raise WorkspaceExecutionContractError(f"duplicate stage id: {stage_id}")
        seen_stage_ids.add(stage_id)

        raw_operations = raw_stage.get("operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            raise WorkspaceExecutionContractError(
                f"stages[{stage_index}].operations must be a non-empty array"
            )
        if len(raw_operations) > MAX_OPERATIONS_PER_STAGE:
            raise WorkspaceExecutionContractError(
                f"stage {stage_id} cannot contain more than {MAX_OPERATIONS_PER_STAGE} operations"
            )
        operations = tuple(
            _parse_operation(
                raw_operation,
                stage_id,
                operation_index,
                seen_operation_ids,
                completed_operation_ids,
            )
            for operation_index, raw_operation in enumerate(raw_operations)
        )
        mutating_operations = [
            operation.operation_id
            for operation in operations
            if operation.kind in _MUTATING_OPERATION_KINDS
        ]
        if mutating_operations and len(operations) != 1:
            raise WorkspaceExecutionContractError(
                f"stage {stage_id} contains mutating operation "
                f"{mutating_operations[0]!r}; mutating operations require an exclusive stage"
            )
        completed_operation_ids.update(operation.operation_id for operation in operations)
        operation_count += len(operations)
        stages.append(WorkspaceStage(stage_id=stage_id, operations=operations))

    if operation_count > MAX_TOTAL_OPERATIONS:
        raise WorkspaceExecutionContractError(
            f"workspace_exec cannot contain more than {MAX_TOTAL_OPERATIONS} operations"
        )
    return tuple(stages)


def _parse_operation(
    raw_operation: object,
    stage_id: str,
    operation_index: int,
    seen_operation_ids: set[str],
    completed_operation_ids: set[str],
) -> WorkspaceOperation:
    label = f"stage {stage_id} operation[{operation_index}]"
    if not isinstance(raw_operation, dict):
        raise WorkspaceExecutionContractError(f"{label} must be an object")
    _reject_unknown_keys(raw_operation, {"id", "kind", "arguments"}, label)
    operation_id = _required_identifier(raw_operation.get("id"), f"{label}.id")
    if operation_id in seen_operation_ids:
        raise WorkspaceExecutionContractError(f"duplicate operation id: {operation_id}")
    seen_operation_ids.add(operation_id)

    kind = str(raw_operation.get("kind") or "").strip()
    if kind not in _OPERATION_ARGUMENTS:
        allowed = ", ".join(sorted(_OPERATION_ARGUMENTS))
        raise WorkspaceExecutionContractError(f"{label}.kind must be one of: {allowed}")
    arguments = raw_operation.get("arguments")
    if not isinstance(arguments, dict):
        raise WorkspaceExecutionContractError(f"{label}.arguments must be an object")
    _reject_unknown_keys(arguments, _OPERATION_ARGUMENTS[kind], f"{label}.arguments")
    missing = sorted(_REQUIRED_ARGUMENTS[kind] - arguments.keys())
    if missing:
        raise WorkspaceExecutionContractError(
            f"{label}.arguments is missing required fields: {', '.join(missing)}"
        )
    _validate_references(arguments, completed_operation_ids, f"{label}.arguments")
    return WorkspaceOperation(operation_id=operation_id, kind=kind, arguments=dict(arguments))


def _validate_references(value: object, available_ids: set[str], label: str) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_references(item, available_ids, f"{label}[{index}]")
        return
    if not isinstance(value, dict):
        return
    if "$ref" in value:
        if set(value) != {"$ref", "path"}:
            raise WorkspaceExecutionContractError(
                f"{label} reference must contain exactly $ref and path"
            )
        operation_id = _required_identifier(value.get("$ref"), f"{label}.$ref")
        if operation_id not in available_ids:
            raise WorkspaceExecutionContractError(
                f"{label} references operation {operation_id!r} before it has completed"
            )
        path = value.get("path")
        if not isinstance(path, list) or len(path) > MAX_REFERENCE_PATH_SEGMENTS:
            raise WorkspaceExecutionContractError(
                f"{label}.path must be an array with at most {MAX_REFERENCE_PATH_SEGMENTS} segments"
            )
        for index, segment in enumerate(path):
            if isinstance(segment, bool) or not isinstance(segment, (str, int)):
                raise WorkspaceExecutionContractError(
                    f"{label}.path[{index}] must be a string or non-negative integer"
                )
            if isinstance(segment, int) and segment < 0:
                raise WorkspaceExecutionContractError(
                    f"{label}.path[{index}] must be a string or non-negative integer"
                )
        return
    for key, item in value.items():
        _validate_references(item, available_ids, f"{label}.{key}")


def _resolve_references(
    value: object,
    completed_operations: dict[str, dict[str, Any]],
) -> Any:
    if isinstance(value, list):
        return [_resolve_references(item, completed_operations) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" not in value:
        return {
            key: _resolve_references(item, completed_operations)
            for key, item in value.items()
        }

    operation_id = str(value["$ref"])
    resolved: Any = completed_operations[operation_id]
    for segment in value["path"]:
        if isinstance(segment, int):
            if not isinstance(resolved, list) or segment >= len(resolved):
                raise WorkspaceExecutionContractError(
                    f"reference {operation_id!r} path segment {segment!r} does not exist"
                )
            resolved = resolved[segment]
            continue
        if not isinstance(resolved, dict) or segment not in resolved:
            raise WorkspaceExecutionContractError(
                f"reference {operation_id!r} path segment {segment!r} does not exist"
            )
        resolved = resolved[segment]
    return resolved


def _execute_operation(operation: WorkspaceOperation, agent: object) -> dict[str, Any]:
    arguments = dict(operation.arguments)
    functions: dict[str, Callable[..., Any]] = {
        "read_file": read_file,
        "search_text": rg_search_text,
        "list_files": rg_list_files,
        "run_command": execute_console_command,
        "apply_patch": apply_patch,
        "update_task_direction": update_task_direction,
    }
    raw_result = functions[operation.kind](agent=agent, **arguments)
    result = _decode_tool_result(raw_result)
    return {
        "id": operation.operation_id,
        "kind": operation.kind,
        "status": str(result.get("status") or "success"),
        "result": result,
    }


def _decode_tool_result(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise WorkspaceExecutionContractError(
            f"workspace operation returned unsupported result type: {type(value).__name__}"
        )
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkspaceExecutionContractError("workspace operation returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise WorkspaceExecutionContractError("workspace operation result must be a JSON object")
    return payload


def _aggregate_status(items: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or "").strip().lower() for item in items}
    if statuses.intersection({"exception", "error", "timeout", "blocked", "stopped"}):
        return "error"
    return "success"


def _required_identifier(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkspaceExecutionContractError(f"{field_name} is required")
    if len(text) > 80:
        raise WorkspaceExecutionContractError(f"{field_name} cannot exceed 80 characters")
    return text


def _reject_unknown_keys(payload: dict[str, Any], allowed: set[str] | frozenset[str], label: str) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise WorkspaceExecutionContractError(f"{label} has unknown fields: {', '.join(unknown)}")
