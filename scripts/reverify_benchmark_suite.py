from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_harness_contract import (
    HarnessSuite,
    HarnessValidationError,
)
from scripts.benchmark_harness_evidence import (
    changed_paths_manifest,
    runner_execution_contract,
    task_evaluation_contract,
)
from scripts.benchmark_harness_imports import validate_frozen_run
from scripts.benchmark_harness_report import (
    build_suite_payload,
    render_comparison_markdown,
)
from scripts.benchmark_verification import (
    git_changed_paths,
    verify_run,
    write_verification,
)
from scripts.long_task_benchmark_artifacts import require_empty_result_dir


def reverify_suite(
    suite: HarnessSuite,
    *,
    source_result_path: Path,
    output_dir: Path,
    runner_ids: set[str] | None = None,
    allow_legacy_workspace_state: bool = False,
) -> dict[str, Any]:
    source_path = source_result_path.resolve()
    source = _read_suite_result(source_path)
    source_runs = _index_source_runs(source["runs"])
    output_dir = output_dir.resolve()
    require_empty_result_dir(output_dir)
    shutil.copy2(suite.manifest_path, output_dir / "manifest.json")
    selected_runner_ids = _selected_runner_ids(suite, runner_ids)
    reverified: list[dict[str, Any]] = []
    for task in suite.tasks:
        for repetition in range(1, suite.repetitions + 1):
            for runner in suite.runners:
                if runner.runner_id not in selected_runner_ids:
                    continue
                case_id = f"{task.task_id}__{runner.runner_id}__r{repetition}"
                source_run = source_runs.get(case_id)
                if source_run is None:
                    raise HarnessValidationError(
                        f"source suite result is missing case {case_id!r}."
                    )
                validate_frozen_run(
                    source_run,
                    task=task,
                    runner=runner,
                    source_path=source_path,
                    require_evaluation_contract=False,
                    require_runner_contract=False,
                    require_workspace_contract=False,
                )
                reverified.append(
                    _reverify_case(
                        task,
                        runner,
                        source_run=source_run,
                        source_path=source_path,
                        output_dir=output_dir,
                        allow_legacy_workspace_state=allow_legacy_workspace_state,
                    )
                )
    payload = build_suite_payload(suite, reverified)
    _write_json(output_dir / "suite-result.json", payload)
    (output_dir / "comparison.md").write_text(
        render_comparison_markdown(payload),
        encoding="utf-8",
    )
    return payload


def _selected_runner_ids(
    suite: HarnessSuite,
    requested: set[str] | None,
) -> set[str]:
    available = {runner.runner_id for runner in suite.runners}
    if not requested:
        return available
    unknown = sorted(requested - available)
    if unknown:
        raise HarnessValidationError(
            f"requested reverify runners do not exist: {', '.join(unknown)}."
        )
    return set(requested)


def _reverify_case(
    task,
    runner,
    *,
    source_run: dict[str, Any],
    source_path: Path,
    output_dir: Path,
    allow_legacy_workspace_state: bool,
) -> dict[str, Any]:
    case_id = str(source_run["case_id"])
    run_dir = output_dir / "runs" / case_id
    run_dir.mkdir(parents=True, exist_ok=False)
    fixture = source_run.get("fixture")
    if not isinstance(fixture, dict):
        raise HarnessValidationError(f"source run {case_id!r} has no fixture object.")
    workspace = Path(str(fixture.get("workspace") or "")).resolve()
    if not workspace.is_dir():
        raise HarnessValidationError(
            f"source run {case_id!r} workspace does not exist: {workspace}."
        )
    changed_paths = git_changed_paths(workspace)
    previous_verification = source_run.get("verification")
    previous_verification = (
        previous_verification if isinstance(previous_verification, dict) else {}
    )
    recorded_paths = previous_verification.get("changed_paths")
    if recorded_paths != changed_paths:
        raise HarnessValidationError(
            f"source run {case_id!r} workspace changed after capture."
        )
    current_workspace_state = changed_paths_manifest(
        changed_paths,
        workspace=workspace,
    )
    legacy_workspace_upgrade = _validate_source_workspace_state(
        source_run,
        current_workspace_state=current_workspace_state,
        case_id=case_id,
        allow_legacy=allow_legacy_workspace_state,
    )
    benchmark = source_run.get("benchmark")
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    result = benchmark.get("result")
    result = result if isinstance(result, dict) else {}
    runner_contract = runner_execution_contract(runner)
    if runner.node_type == "agent":
        summary = result.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        captured_policy = summary.get("runtime_policy_manifest")
        if captured_policy != runner_contract["effective_runtime_policy"]:
            raise HarnessValidationError(
                f"source run {case_id!r} effective RuntimePolicy does not match "
                "the current runner contract."
            )
    benchmark_status = str(
        result.get("status")
        or previous_verification.get("benchmark_status")
        or ""
    )
    verification = verify_run(
        task,
        workspace=workspace,
        run_dir=run_dir,
        benchmark_status=benchmark_status,
        benchmark_output=str(result.get("output") or ""),
    )
    write_verification(run_dir / "verification.json", verification)
    updated = copy.deepcopy(source_run)
    updated["runner_contract"] = runner_contract
    updated["evaluation_contract"] = task_evaluation_contract(task)
    updated["verification"] = verification
    updated["workspace_state"] = current_workspace_state
    updated["execution_source"] = {
        "kind": "reverified",
        "source_suite_result": str(source_path),
        "source_execution": source_run.get("execution_source"),
        "legacy_workspace_state_upgraded": legacy_workspace_upgrade,
    }
    return updated


def _validate_source_workspace_state(
    source_run: dict[str, Any],
    *,
    current_workspace_state: dict[str, Any],
    case_id: str,
    allow_legacy: bool,
) -> bool:
    captured = source_run.get("workspace_state")
    if captured == current_workspace_state:
        return False
    captured = captured if isinstance(captured, dict) else {}
    legacy_matches_paths = (
        captured.get("count") == current_workspace_state["count"]
        and captured.get("sha256") == current_workspace_state["sha256"]
        and "entries" not in captured
    )
    if allow_legacy and legacy_matches_paths:
        return True
    if legacy_matches_paths:
        raise HarnessValidationError(
            f"source run {case_id!r} has only a legacy path-level workspace "
            "contract; pass --upgrade-legacy-workspace-state to capture content "
            "hashes during explicit reverification."
        )
    raise HarnessValidationError(
        f"source run {case_id!r} workspace artifact contract does not match."
    )


def _index_source_runs(runs: object) -> dict[str, dict[str, Any]]:
    if not isinstance(runs, list):
        raise HarnessValidationError("source suite result must contain a runs array.")
    indexed: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise HarnessValidationError("source suite result contains a non-object run.")
        case_id = str(run.get("case_id") or "")
        if not case_id:
            raise HarnessValidationError("source suite result contains a run without case_id.")
        if case_id in indexed:
            raise HarnessValidationError(
                f"source suite result contains duplicate case {case_id!r}."
            )
        indexed[case_id] = run
    return indexed


def _read_suite_result(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HarnessValidationError(f"source suite result does not exist: {path}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessValidationError(
            f"invalid source suite result JSON in {path}: {exc}."
        ) from exc
    if not isinstance(payload, dict):
        raise HarnessValidationError("source suite result must be an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-run the current verifier against immutable benchmark workspaces."
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-suite-result", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--runner-id",
        action="append",
        default=[],
        help="Reverify only this runner id; repeat to select multiple runners.",
    )
    parser.add_argument(
        "--upgrade-legacy-workspace-state",
        action="store_true",
        help=(
            "Explicitly upgrade a legacy path-only workspace contract by hashing the "
            "current frozen workspace during reverification."
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    payload = reverify_suite(
        HarnessSuite.load(args.manifest),
        source_result_path=Path(args.source_suite_result),
        output_dir=Path(args.output_dir),
        runner_ids=set(args.runner_id) or None,
        allow_legacy_workspace_state=args.upgrade_legacy_workspace_state,
    )
    print(render_comparison_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
