from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from scripts.benchmark_harness_contract import CommandSpec, TaskSpec


def run_command(command: CommandSpec, *, cwd: Path, log_dir: Path) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    try:
        process = subprocess.run(
            _resolved_argv(command.argv),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=command.timeout_seconds,
            check=False,
        )
        exit_code = process.returncode
        stdout = process.stdout.decode("utf-8", errors="replace")
        stderr = process.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = _decode_timeout_stream(exc.stdout)
        stderr = _decode_timeout_stream(exc.stderr)
    duration_ms = int((time.monotonic() - started) * 1000)
    (log_dir / f"{command.command_id}.stdout.txt").write_text(stdout, encoding="utf-8")
    (log_dir / f"{command.command_id}.stderr.txt").write_text(stderr, encoding="utf-8")
    return {
        "id": command.command_id,
        "argv": list(command.argv),
        "required": command.required,
        "weight": command.weight,
        "timeout_seconds": command.timeout_seconds,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "passed": exit_code == 0 and not timed_out,
        "stdout_log": f"{command.command_id}.stdout.txt",
        "stderr_log": f"{command.command_id}.stderr.txt",
    }


def run_setup(task: TaskSpec, *, workspace: Path, run_dir: Path) -> list[dict[str, Any]]:
    results = [
        run_command(command, cwd=workspace, log_dir=run_dir / "setup-logs")
        for command in task.setup
    ]
    failed = [result["id"] for result in results if not result["passed"]]
    if failed:
        raise RuntimeError(f"Fixture setup failed: {', '.join(failed)}.")
    return results


def verify_run(
    task: TaskSpec,
    *,
    workspace: Path,
    run_dir: Path,
    benchmark_status: str,
    benchmark_output: str = "",
) -> dict[str, Any]:
    command_results = [
        run_command(command, cwd=workspace, log_dir=run_dir / "verification-logs")
        for command in task.verification
    ]
    changed_paths = git_changed_paths(workspace)
    path_checks = _path_checks(task, changed_paths)
    output_checks = [
        {
            "id": check.check_id,
            "pattern": check.pattern,
            "required": check.required,
            "weight": check.weight,
            "passed": re.search(
                check.pattern,
                benchmark_output,
                flags=re.IGNORECASE | re.MULTILINE,
            )
            is not None,
        }
        for check in task.output_checks
    ]
    required_commands_passed = all(
        result["passed"] for result in command_results if result["required"]
    )
    required_output_checks_passed = all(
        result["passed"] for result in output_checks if result["required"]
    )
    weighted_results = [*command_results, *output_checks]
    total_weight = sum(int(result["weight"]) for result in weighted_results)
    passed_weight = sum(
        int(result["weight"]) for result in weighted_results if result["passed"]
    )
    command_score = 100.0 * passed_weight / total_weight if total_weight else 0.0
    path_gate_passed = all(check["passed"] for check in path_checks)
    completed = (
        benchmark_status == "completed"
        and required_commands_passed
        and required_output_checks_passed
        and path_gate_passed
    )
    return {
        "schema_version": 1,
        "completed": completed,
        "completion_score": round(command_score, 3),
        "benchmark_status": benchmark_status,
        "required_commands_passed": required_commands_passed,
        "required_output_checks_passed": required_output_checks_passed,
        "path_gate_passed": path_gate_passed,
        "commands": command_results,
        "output_checks": output_checks,
        "changed_paths": changed_paths,
        "path_checks": path_checks,
    }


def git_changed_paths(workspace: Path) -> list[str]:
    process = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git status failed for {workspace}: {stderr}")
    records = process.stdout.decode("utf-8", errors="strict").split("\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise RuntimeError(f"Unexpected git status record: {record!r}")
        status = record[:2]
        paths.append(record[3:].replace("\\", "/"))
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise RuntimeError("Git status rename/copy record is missing its source path.")
            if "R" in status:
                paths.append(records[index].replace("\\", "/"))
            index += 1
    return sorted(paths)


def write_verification(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _path_checks(task: TaskSpec, changed_paths: list[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for pattern in task.required_changed_paths:
        matches = [path for path in changed_paths if fnmatch.fnmatch(path, pattern)]
        checks.append(
            {
                "kind": "required",
                "pattern": pattern,
                "passed": bool(matches),
                "matches": matches,
            }
        )
    for pattern in task.forbidden_changed_paths:
        matches = [path for path in changed_paths if fnmatch.fnmatch(path, pattern)]
        checks.append(
            {
                "kind": "forbidden",
                "pattern": pattern,
                "passed": not matches,
                "matches": matches,
            }
        )
    return checks


def _decode_timeout_stream(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _resolved_argv(argv: tuple[str, ...]) -> list[str]:
    executable = shutil.which(argv[0])
    if executable is None:
        raise FileNotFoundError(f"Command executable was not found: {argv[0]}")
    return [executable, *argv[1:]]


__all__ = [
    "git_changed_paths",
    "run_command",
    "run_setup",
    "verify_run",
    "write_verification",
]
