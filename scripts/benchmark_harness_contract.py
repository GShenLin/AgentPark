from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from scripts.benchmark_harness_task_contract import (
    CommandSpec,
    FixtureSpec,
    HarnessValidationError,
    OracleSpec,
    TaskSpec,
    _identifier,
    _integer,
    _non_empty_string,
    _object,
    _path,
    _string,
    _unique_ids,
)
from scripts.benchmark_harness_output import OutputCheckSpec


@dataclass(frozen=True)
class RunnerSpec:
    runner_id: str
    node_type: str
    provider_id: str
    profile: str
    runtime_policy_file: Path | None

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        field: str,
        base_dir: Path,
    ) -> "RunnerSpec":
        data = _object(
            payload,
            field=field,
            required={"id", "node_type", "provider_id"},
            optional={"profile", "runtime_policy_file"},
        )
        node_type = _non_empty_string(data["node_type"], field=f"{field}.node_type")
        if node_type not in {"agent", "codex"}:
            raise HarnessValidationError(f"{field}.node_type must be 'agent' or 'codex'.")
        runtime_policy_file = None
        if data.get("runtime_policy_file") is not None:
            runtime_policy_file = _path(
                data["runtime_policy_file"],
                field=f"{field}.runtime_policy_file",
                base_dir=base_dir,
            )
            if not runtime_policy_file.is_file():
                raise HarnessValidationError(
                    f"{field}.runtime_policy_file does not exist: {runtime_policy_file}."
                )
            if node_type != "agent":
                raise HarnessValidationError(
                    f"{field}.runtime_policy_file is only valid for an agent runner."
                )
        profile = _string(data.get("profile", ""), field=f"{field}.profile").strip()
        if node_type == "agent" and not profile:
            raise HarnessValidationError(f"{field}.profile is required for an agent runner.")
        return cls(
            runner_id=_identifier(data["id"], field=f"{field}.id"),
            node_type=node_type,
            provider_id=_non_empty_string(data["provider_id"], field=f"{field}.provider_id"),
            profile=profile,
            runtime_policy_file=runtime_policy_file,
        )


@dataclass(frozen=True)
class HarnessSuite:
    suite_id: str
    repetitions: int
    tasks: tuple[TaskSpec, ...]
    runners: tuple[RunnerSpec, ...]
    manifest_path: Path

    @classmethod
    def load(cls, path: str | Path) -> "HarnessSuite":
        manifest_path = Path(path).resolve()
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HarnessValidationError(
                f"Invalid harness JSON in {manifest_path}: {exc}."
            ) from exc
        data = _object(
            payload,
            field="harness",
            required={"schema_version", "suite_id", "tasks", "runners"},
            optional={"repetitions"},
        )
        if data["schema_version"] != 1:
            raise HarnessValidationError("harness.schema_version must be 1.")
        tasks_payload = data["tasks"]
        runners_payload = data["runners"]
        if not isinstance(tasks_payload, list) or not tasks_payload:
            raise HarnessValidationError("harness.tasks must be a non-empty array.")
        if not isinstance(runners_payload, list) or len(runners_payload) < 2:
            raise HarnessValidationError(
                "harness.runners must contain at least two runners."
            )
        base_dir = manifest_path.parent
        tasks = tuple(
            TaskSpec.from_payload(
                item,
                field=f"harness.tasks[{index}]",
                base_dir=base_dir,
            )
            for index, item in enumerate(tasks_payload)
        )
        runners = tuple(
            RunnerSpec.from_payload(
                item,
                field=f"harness.runners[{index}]",
                base_dir=base_dir,
            )
            for index, item in enumerate(runners_payload)
        )
        _unique_ids([task.task_id for task in tasks], field="harness.tasks")
        _unique_ids([runner.runner_id for runner in runners], field="harness.runners")
        return cls(
            suite_id=_identifier(data["suite_id"], field="harness.suite_id"),
            repetitions=_integer(
                data.get("repetitions", 1),
                field="harness.repetitions",
                minimum=1,
                maximum=10,
            ),
            tasks=tasks,
            runners=runners,
            manifest_path=manifest_path,
        )


__all__ = [
    "CommandSpec",
    "FixtureSpec",
    "HarnessSuite",
    "HarnessValidationError",
    "OracleSpec",
    "OutputCheckSpec",
    "RunnerSpec",
    "TaskSpec",
]
