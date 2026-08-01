from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_harness_contract import HarnessSuite, RunnerSpec, TaskSpec
from scripts.benchmark_harness_evidence import (
    changed_paths_manifest,
    runner_execution_contract,
    task_evaluation_contract,
    task_fixture_contract,
    task_input_contract,
    validate_profile_ab_runner_contracts,
)
from scripts.benchmark_harness_imports import load_imported_runs
from scripts.benchmark_harness_report import build_suite_payload
from scripts.benchmark_harness_report import render_comparison_markdown
from scripts.benchmark_long_task import summarize_events
from scripts.benchmark_verification import run_setup, verify_run, write_verification
from scripts.long_task_benchmark_artifacts import require_empty_result_dir


def run_suite(
    suite: HarnessSuite,
    *,
    output_dir: Path,
    imported_result_paths: list[Path] | None = None,
) -> dict[str, Any]:
    validate_profile_ab_runner_contracts(
        [runner_execution_contract(runner) for runner in suite.runners]
    )
    output_dir = output_dir.resolve()
    require_empty_result_dir(output_dir)
    shutil.copy2(suite.manifest_path, output_dir / "manifest.json")
    run_results = load_imported_runs(suite, imported_result_paths or [])
    completed_case_ids = {run["case_id"] for run in run_results}
    for task in suite.tasks:
        for repetition in range(1, suite.repetitions + 1):
            for runner in suite.runners:
                case_id = f"{task.task_id}__{runner.runner_id}__r{repetition}"
                if case_id in completed_case_ids:
                    continue
                run_results.append(
                    _run_case(
                        task,
                        runner,
                        repetition=repetition,
                        output_dir=output_dir,
                    )
                )
                _write_json(
                    output_dir / "suite-result.partial.json",
                    build_suite_payload(suite, run_results),
                )
    payload = build_suite_payload(suite, run_results)
    _write_json(output_dir / "suite-result.json", payload)
    (output_dir / "comparison.md").write_text(
        render_comparison_markdown(payload),
        encoding="utf-8",
    )
    partial = output_dir / "suite-result.partial.json"
    if partial.exists():
        partial.unlink()
    return payload


def _run_case(
    task: TaskSpec,
    runner: RunnerSpec,
    *,
    repetition: int,
    output_dir: Path,
) -> dict[str, Any]:
    case_id = f"{task.task_id}__{runner.runner_id}__r{repetition}"
    run_dir = output_dir / "runs" / case_id
    run_dir.mkdir(parents=True, exist_ok=False)
    input_contract = task_input_contract(task)
    evaluation_contract = task_evaluation_contract(task)
    runner_contract = runner_execution_contract(runner)
    expected_fixture = task_fixture_contract(task)
    workspace = run_dir / "workspace"
    fixture = _prepare_fixture(task, workspace=workspace)
    _require_fixture_match(expected_fixture, fixture, case_id=case_id)
    setup_results = run_setup(task, workspace=workspace, run_dir=run_dir)
    benchmark_dir = run_dir / "benchmark"
    command = _benchmark_command(
        task,
        runner,
        workspace=workspace,
        benchmark_dir=benchmark_dir,
    )
    started = time.monotonic()
    timed_out = False
    process_result: dict[str, Any]
    try:
        process = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=task.benchmark_timeout_seconds,
            check=False,
        )
        process_result = {
            "exit_code": process.returncode,
            "stdout": process.stdout.decode("utf-8", errors="replace"),
            "stderr": process.stderr.decode("utf-8", errors="replace"),
        }
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        process_result = {
            "exit_code": None,
            "stdout": _decode_timeout_stream(exc.stdout),
            "stderr": _decode_timeout_stream(exc.stderr),
        }
    wall_duration_ms = int((time.monotonic() - started) * 1000)
    (run_dir / "benchmark.stdout.txt").write_text(process_result["stdout"], encoding="utf-8")
    (run_dir / "benchmark.stderr.txt").write_text(process_result["stderr"], encoding="utf-8")
    benchmark_result = _read_json_optional(benchmark_dir / "result.json")
    benchmark_status = str(benchmark_result.get("status") or "")
    if timed_out:
        benchmark_status = "timeout"
        if not benchmark_result:
            benchmark_result = _timeout_benchmark_result(
                benchmark_dir / "events.jsonl",
                duration_ms=wall_duration_ms,
                timeout_seconds=task.benchmark_timeout_seconds,
            )
    elif not benchmark_status:
        benchmark_status = "error"
    verification = verify_run(
        task,
        workspace=workspace,
        run_dir=run_dir,
        benchmark_status=benchmark_status,
        benchmark_output=str(benchmark_result.get("output") or ""),
    )
    _require_unchanged_contracts(
        task,
        runner,
        input_contract=input_contract,
        evaluation_contract=evaluation_contract,
        runner_contract=runner_contract,
        case_id=case_id,
    )
    write_verification(run_dir / "verification.json", verification)
    return {
        "case_id": case_id,
        "task_id": task.task_id,
        "category": task.category,
        "source_session_id": task.source_session_id,
        "source_turn_id": task.source_turn_id,
        "input_contract": input_contract,
        "evaluation_contract": evaluation_contract,
        "runner_id": runner.runner_id,
        "node_type": runner.node_type,
        "provider_id": runner.provider_id,
        "runner_contract": runner_contract,
        "repetition": repetition,
        "fixture": fixture,
        "setup": setup_results,
        "benchmark": {
            "command": command,
            "timed_out": timed_out,
            "timeout_seconds": task.benchmark_timeout_seconds,
            "exit_code": process_result["exit_code"],
            "wall_duration_ms": wall_duration_ms,
            "result_path": "benchmark/result.json",
            "result": benchmark_result,
        },
        "verification": verification,
        "workspace_state": changed_paths_manifest(
            verification["changed_paths"],
            workspace=workspace,
        ),
        "execution_source": {"kind": "local"},
    }


def _require_fixture_match(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    case_id: str,
) -> None:
    for field in ("requested_revision", "resolved_revision", "submodules"):
        if actual.get(field) != expected[field]:
            raise RuntimeError(
                f"Benchmark fixture changed while preparing case {case_id!r}: {field}."
            )


def _require_unchanged_contracts(
    task: TaskSpec,
    runner: RunnerSpec,
    *,
    input_contract: dict[str, Any],
    evaluation_contract: dict[str, Any],
    runner_contract: dict[str, Any],
    case_id: str,
) -> None:
    current = {
        "input": task_input_contract(task),
        "evaluation": task_evaluation_contract(task),
        "runner": runner_execution_contract(runner),
    }
    expected = {
        "input": input_contract,
        "evaluation": evaluation_contract,
        "runner": runner_contract,
    }
    changed = [name for name in expected if current[name] != expected[name]]
    if changed:
        raise RuntimeError(
            f"Benchmark contracts changed while case {case_id!r} was running: "
            f"{', '.join(changed)}."
        )


def _prepare_fixture(task: TaskSpec, *, workspace: Path) -> dict[str, Any]:
    clone = subprocess.run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            "--quiet",
            "--no-checkout",
            str(task.fixture.repository),
            str(workspace),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if clone.returncode != 0:
        raise RuntimeError(
            "Fixture clone failed: "
            + clone.stderr.decode("utf-8", errors="replace").strip()
        )
    checkout = subprocess.run(
        ["git", "-C", str(workspace), "checkout", "--quiet", "--detach", task.fixture.revision],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if checkout.returncode != 0:
        raise RuntimeError(
            "Fixture checkout failed: "
            + checkout.stderr.decode("utf-8", errors="replace").strip()
        )
    if task.fixture.submodules:
        submodules = subprocess.run(
            ["git", "-C", str(workspace), "submodule", "update", "--init", "--recursive"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if submodules.returncode != 0:
            raise RuntimeError(
                "Fixture submodule setup failed: "
                + submodules.stderr.decode("utf-8", errors="replace").strip()
            )
    revision = _git_text(workspace, "rev-parse", "HEAD").strip()
    return {
        "repository": str(task.fixture.repository),
        "requested_revision": task.fixture.revision,
        "resolved_revision": revision,
        "workspace": str(workspace),
        "submodules": task.fixture.submodules,
    }


def _benchmark_command(
    task: TaskSpec,
    runner: RunnerSpec,
    *,
    workspace: Path,
    benchmark_dir: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "benchmark_long_task.py"),
        "--node-type",
        runner.node_type,
        "--workspace",
        str(workspace),
        "--prompt-file",
        str(task.prompt_file),
        "--result-dir",
        str(benchmark_dir),
        "--provider-id",
        runner.provider_id,
    ]
    if runner.profile:
        command.extend(["--profile", runner.profile])
    if runner.runtime_policy_file is not None:
        command.extend(["--runtime-policy-file", str(runner.runtime_policy_file)])
    if task.conversation_context_file is not None:
        command.extend(
            [
                "--conversation-context-file",
                str(task.conversation_context_file),
            ]
        )
    return command


def _git_text(workspace: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(workspace), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace").strip())
    return process.stdout.decode("utf-8", errors="strict")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json_optional(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _timeout_benchmark_result(
    event_journal: Path,
    *,
    duration_ms: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if event_journal.is_file():
        for line in event_journal.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
    return {
        "schema_version": 2,
        "status": "timeout",
        "error": f"Benchmark timed out after {timeout_seconds} seconds.",
        "event_journal": "events.jsonl",
        "summary": summarize_events(events, duration_ms=duration_ms, output=""),
    }


def _decode_timeout_stream(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a reproducible Agent/Codex benchmark suite.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--import-suite-result",
        action="append",
        default=[],
        help="Reuse compatible frozen runs after strict input/fixture/runner validation.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    suite = HarnessSuite.load(args.manifest)
    payload = run_suite(
        suite,
        output_dir=Path(args.output_dir),
        imported_result_paths=[Path(path) for path in args.import_suite_result],
    )
    print(render_comparison_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
