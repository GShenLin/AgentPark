from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.benchmark_harness_output import OutputCheckSpec


class HarnessValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    required: bool
    weight: int

    @classmethod
    def from_payload(cls, payload: object, *, field: str) -> "CommandSpec":
        data = _object(
            payload,
            field=field,
            required={"id", "argv", "timeout_seconds"},
            optional={"required", "weight"},
        )
        return cls(
            command_id=_identifier(data["id"], field=f"{field}.id"),
            argv=_string_array(data["argv"], field=f"{field}.argv", allow_empty=False),
            timeout_seconds=_integer(
                data["timeout_seconds"],
                field=f"{field}.timeout_seconds",
                minimum=1,
                maximum=86400,
            ),
            required=_boolean(data.get("required", True), field=f"{field}.required"),
            weight=_integer(
                data.get("weight", 1),
                field=f"{field}.weight",
                minimum=1,
                maximum=1000,
            ),
        )


@dataclass(frozen=True)
class FixtureSpec:
    repository: Path
    revision: str
    submodules: bool

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        field: str,
        base_dir: Path,
    ) -> "FixtureSpec":
        data = _object(
            payload,
            field=field,
            required={"repository", "revision"},
            optional={"submodules"},
        )
        repository = _path(
            data["repository"],
            field=f"{field}.repository",
            base_dir=base_dir,
        )
        if not repository.is_dir():
            raise HarnessValidationError(
                f"{field}.repository does not exist: {repository}."
            )
        return cls(
            repository=repository,
            revision=_non_empty_string(data["revision"], field=f"{field}.revision"),
            submodules=_boolean(
                data.get("submodules", False),
                field=f"{field}.submodules",
            ),
        )


@dataclass(frozen=True)
class OracleSpec:
    source: str
    reference: str
    acceptance_file: Path

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        field: str,
        base_dir: Path,
    ) -> "OracleSpec":
        data = _object(
            payload,
            field=field,
            required={"source", "reference", "acceptance_file"},
        )
        source = _non_empty_string(data["source"], field=f"{field}.source")
        allowed_sources = {
            "source-session",
            "user-specification",
            "independent-specification",
        }
        if source not in allowed_sources:
            raise HarnessValidationError(
                f"{field}.source must be one of: {', '.join(sorted(allowed_sources))}."
            )
        acceptance_file = _required_file(
            data["acceptance_file"],
            field=f"{field}.acceptance_file",
            base_dir=base_dir,
        )
        return cls(
            source=source,
            reference=_non_empty_string(
                data["reference"],
                field=f"{field}.reference",
            ),
            acceptance_file=acceptance_file,
        )


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    category: str
    prompt_file: Path
    conversation_context_file: Path | None
    source_session_id: str
    source_turn_id: str
    oracle: OracleSpec
    fixture: FixtureSpec
    setup: tuple[CommandSpec, ...]
    verification: tuple[CommandSpec, ...]
    output_checks: tuple[OutputCheckSpec, ...]
    required_changed_paths: tuple[str, ...]
    forbidden_changed_paths: tuple[str, ...]
    benchmark_timeout_seconds: int

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        field: str,
        base_dir: Path,
    ) -> "TaskSpec":
        data = _object(
            payload,
            field=field,
            required={"id", "category", "prompt_file", "oracle", "fixture"},
            optional={
                "conversation_context_file",
                "source_session_id",
                "source_turn_id",
                "setup",
                "verification",
                "output_checks",
                "required_changed_paths",
                "forbidden_changed_paths",
                "benchmark_timeout_seconds",
            },
        )
        prompt_file = _required_file(
            data["prompt_file"],
            field=f"{field}.prompt_file",
            base_dir=base_dir,
        )
        context_file = None
        if data.get("conversation_context_file") is not None:
            context_file = _required_file(
                data["conversation_context_file"],
                field=f"{field}.conversation_context_file",
                base_dir=base_dir,
            )
        setup = _commands(data.get("setup", []), field=f"{field}.setup")
        verification = _commands(
            data.get("verification", []),
            field=f"{field}.verification",
        )
        output_checks = _output_checks(
            data.get("output_checks", []),
            field=f"{field}.output_checks",
        )
        if not verification and not output_checks:
            raise HarnessValidationError(
                f"{field} must define verification commands or output_checks."
            )
        return cls(
            task_id=_identifier(data["id"], field=f"{field}.id"),
            category=_non_empty_string(data["category"], field=f"{field}.category"),
            prompt_file=prompt_file,
            conversation_context_file=context_file,
            source_session_id=_string(
                data.get("source_session_id", ""),
                field=f"{field}.source_session_id",
            ).strip(),
            source_turn_id=_string(
                data.get("source_turn_id", ""),
                field=f"{field}.source_turn_id",
            ).strip(),
            oracle=OracleSpec.from_payload(
                data["oracle"],
                field=f"{field}.oracle",
                base_dir=base_dir,
            ),
            fixture=FixtureSpec.from_payload(
                data["fixture"],
                field=f"{field}.fixture",
                base_dir=base_dir,
            ),
            setup=setup,
            verification=verification,
            output_checks=output_checks,
            required_changed_paths=_string_array(
                data.get("required_changed_paths", []),
                field=f"{field}.required_changed_paths",
                allow_empty=True,
            ),
            forbidden_changed_paths=_string_array(
                data.get("forbidden_changed_paths", []),
                field=f"{field}.forbidden_changed_paths",
                allow_empty=True,
            ),
            benchmark_timeout_seconds=_integer(
                data.get("benchmark_timeout_seconds", 3600),
                field=f"{field}.benchmark_timeout_seconds",
                minimum=1,
                maximum=86400,
            ),
        )


def _commands(payload: object, *, field: str) -> tuple[CommandSpec, ...]:
    if not isinstance(payload, list):
        raise HarnessValidationError(f"{field} must be an array.")
    commands = tuple(
        CommandSpec.from_payload(item, field=f"{field}[{index}]")
        for index, item in enumerate(payload)
    )
    _unique_ids([command.command_id for command in commands], field=field)
    return commands


def _output_checks(payload: object, *, field: str) -> tuple[OutputCheckSpec, ...]:
    if not isinstance(payload, list):
        raise HarnessValidationError(f"{field} must be an array.")
    checks = tuple(
        OutputCheckSpec.from_payload(
            item,
            field=f"{field}[{index}]",
            error_type=HarnessValidationError,
        )
        for index, item in enumerate(payload)
    )
    _unique_ids([check.check_id for check in checks], field=field)
    return checks


def _object(
    payload: object,
    *,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HarnessValidationError(f"{field} must be an object.")
    allowed = required | (optional or set())
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - allowed)
    if missing:
        raise HarnessValidationError(
            f"{field} is missing fields: {', '.join(missing)}."
        )
    if unknown:
        raise HarnessValidationError(
            f"{field} has unknown fields: {', '.join(unknown)}."
        )
    return dict(payload)


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise HarnessValidationError(f"{field} must be a string.")
    return value


def _non_empty_string(value: object, *, field: str) -> str:
    text = _string(value, field=field).strip()
    if not text:
        raise HarnessValidationError(f"{field} must not be empty.")
    return text


def _identifier(value: object, *, field: str) -> str:
    text = _non_empty_string(value, field=field)
    if any(not (char.isalnum() or char in {"-", "_", "."}) for char in text):
        raise HarnessValidationError(f"{field} contains invalid characters.")
    return text


def _integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HarnessValidationError(f"{field} must be an integer.")
    if value < minimum or value > maximum:
        raise HarnessValidationError(
            f"{field} must be between {minimum} and {maximum}."
        )
    return value


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise HarnessValidationError(f"{field} must be a boolean.")
    return value


def _string_array(
    value: object,
    *,
    field: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise HarnessValidationError(f"{field} must be an array of strings.")
    output = tuple(
        _non_empty_string(item, field=f"{field}[{index}]")
        for index, item in enumerate(value)
    )
    if not allow_empty and not output:
        raise HarnessValidationError(f"{field} must not be empty.")
    if len(set(output)) != len(output):
        raise HarnessValidationError(f"{field} must not contain duplicates.")
    return output


def _path(value: object, *, field: str, base_dir: Path) -> Path:
    text = _non_empty_string(value, field=field)
    candidate = Path(text).expanduser()
    return (candidate if candidate.is_absolute() else base_dir / candidate).resolve()


def _required_file(value: object, *, field: str, base_dir: Path) -> Path:
    path = _path(value, field=field, base_dir=base_dir)
    if not path.is_file():
        raise HarnessValidationError(f"{field} does not exist: {path}.")
    if not path.read_text(encoding="utf-8").strip():
        raise HarnessValidationError(f"{field} must not be empty: {path}.")
    return path


def _unique_ids(values: list[str], *, field: str) -> None:
    if len(values) != len(set(values)):
        raise HarnessValidationError(f"{field} ids must be unique.")


__all__ = [
    "CommandSpec",
    "FixtureSpec",
    "HarnessValidationError",
    "OracleSpec",
    "TaskSpec",
]
