from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from scripts.benchmark_harness_contract import HarnessSuite, HarnessValidationError
from scripts.benchmark_harness_evidence import (
    changed_paths_manifest,
    runner_execution_contract,
    task_evaluation_contract,
    task_fixture_contract,
    task_input_contract,
)
from scripts.benchmark_verification import git_changed_paths


def load_imported_runs(
    suite: HarnessSuite,
    result_paths: list[Path],
) -> list[dict[str, Any]]:
    tasks = {task.task_id: task for task in suite.tasks}
    runners = {runner.runner_id: runner for runner in suite.runners}
    imported: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for raw_path in result_paths:
        path = raw_path.resolve()
        payload = _read_result(path)
        matched = 0
        for candidate in payload["runs"]:
            if not isinstance(candidate, dict):
                raise HarnessValidationError(
                    f"imported suite result contains a non-object run: {path}."
                )
            runner_id = str(candidate.get("runner_id") or "")
            if runner_id not in runners:
                continue
            matched += 1
            task_id = str(candidate.get("task_id") or "")
            task = tasks.get(task_id)
            if task is None:
                raise HarnessValidationError(
                    f"imported run references unknown task {task_id!r}: {path}."
                )
            runner = runners[runner_id]
            validate_frozen_run(
                candidate,
                task=task,
                runner=runner,
                source_path=path,
                require_evaluation_contract=True,
                require_runner_contract=True,
                require_workspace_contract=True,
            )
            case_id = str(candidate.get("case_id") or "")
            if case_id in seen_case_ids:
                raise HarnessValidationError(
                    f"duplicate imported case_id {case_id!r}."
                )
            seen_case_ids.add(case_id)
            copied = copy.deepcopy(candidate)
            copied["execution_source"] = {
                "kind": "imported",
                "suite_result": str(path),
            }
            imported.append(copied)
        if matched == 0:
            raise HarnessValidationError(
                f"imported suite result has no runners used by this manifest: {path}."
            )
    return imported


def _read_result(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HarnessValidationError(f"imported suite result does not exist: {path}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessValidationError(
            f"invalid imported suite result JSON in {path}: {exc}."
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
        raise HarnessValidationError(
            f"imported suite result must contain a runs array: {path}."
        )
    return payload


def validate_frozen_run(
    run: dict[str, Any],
    *,
    task,
    runner,
    source_path: Path,
    require_evaluation_contract: bool,
    require_runner_contract: bool,
    require_workspace_contract: bool,
) -> None:
    expected_contract = task_input_contract(task)
    if run.get("input_contract") != expected_contract:
        raise HarnessValidationError(
            f"imported run input contract does not match task {task.task_id}: "
            f"{source_path}."
        )
    if (
        require_evaluation_contract
        and run.get("evaluation_contract") != task_evaluation_contract(task)
    ):
        raise HarnessValidationError(
            f"imported run evaluation contract does not match task {task.task_id}: "
            f"{source_path}."
        )
    if (
        require_runner_contract
        and run.get("runner_contract") != runner_execution_contract(runner)
    ):
        raise HarnessValidationError(
            f"imported run runner contract does not match runner {runner.runner_id}: "
            f"{source_path}."
        )
    fixture = run.get("fixture")
    fixture = fixture if isinstance(fixture, dict) else {}
    expected_fixture = task_fixture_contract(task)
    if any(
        fixture.get(field) != expected_fixture[field]
        for field in ("requested_revision", "resolved_revision", "submodules")
    ):
        raise HarnessValidationError(
            f"imported run fixture contract does not match task {task.task_id}: "
            f"{source_path}."
        )
    if require_workspace_contract:
        _validate_workspace_state(run, fixture=fixture, source_path=source_path)
    if str(run.get("node_type") or "") != runner.node_type:
        raise HarnessValidationError(
            f"imported run node_type does not match runner {runner.runner_id}: "
            f"{source_path}."
        )
    if str(run.get("provider_id") or "") != runner.provider_id:
        raise HarnessValidationError(
            f"imported run provider_id does not match runner {runner.runner_id}: "
            f"{source_path}."
        )


def _validate_workspace_state(
    run: dict[str, Any],
    *,
    fixture: dict[str, Any],
    source_path: Path,
) -> None:
    workspace = Path(str(fixture.get("workspace") or "")).resolve()
    if not workspace.is_dir():
        raise HarnessValidationError(
            f"imported run workspace does not exist: {workspace}: {source_path}."
        )
    verification = run.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    changed_paths = verification.get("changed_paths")
    if not isinstance(changed_paths, list) or not all(
        isinstance(path, str) for path in changed_paths
    ):
        raise HarnessValidationError(
            f"imported run has no valid changed_paths evidence: {source_path}."
        )
    current_paths = git_changed_paths(workspace)
    if changed_paths != current_paths:
        raise HarnessValidationError(
            f"imported run workspace changed after capture: {source_path}."
        )
    expected = changed_paths_manifest(current_paths, workspace=workspace)
    if run.get("workspace_state") != expected:
        raise HarnessValidationError(
            f"imported run workspace artifact contract does not match: {source_path}."
        )


__all__ = ["load_imported_runs", "validate_frozen_run"]
