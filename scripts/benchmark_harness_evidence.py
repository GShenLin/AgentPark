from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from scripts.benchmark_harness_contract import CommandSpec, RunnerSpec, TaskSpec
from scripts.long_task_benchmark_artifacts import resolve_agent_profile
from src.web_backend.profile_metadata import profile_ab_comparison_contract


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def task_input_contract(task: TaskSpec) -> dict[str, Any]:
    return {
        "prompt": file_manifest(task.prompt_file),
        "conversation_context": (
            file_manifest(task.conversation_context_file)
            if task.conversation_context_file is not None
            else None
        ),
        "oracle": {
            "source": task.oracle.source,
            "reference": task.oracle.reference,
            "acceptance": file_manifest(task.oracle.acceptance_file),
            "visibility": "verifier-only",
        },
    }


def task_evaluation_contract(task: TaskSpec) -> dict[str, Any]:
    commands = [
        *_command_contracts(task.setup, phase="setup"),
        *_command_contracts(task.verification, phase="verification"),
    ]
    referenced_files: dict[str, dict[str, Any]] = {}
    for command in commands:
        for reference in command.pop("referenced_files"):
            referenced_files[reference["path"]] = reference
    engine_files = (
        PROJECT_ROOT / "scripts" / "benchmark_verification.py",
        PROJECT_ROOT / "scripts" / "benchmark_harness_output.py",
    )
    return {
        "schema_version": 1,
        "commands": commands,
        "output_checks": [
            {
                "id": check.check_id,
                "pattern": check.pattern,
                "required": check.required,
                "weight": check.weight,
            }
            for check in task.output_checks
        ],
        "path_gates": {
            "required": list(task.required_changed_paths),
            "forbidden": list(task.forbidden_changed_paths),
        },
        "referenced_files": [
            referenced_files[path] for path in sorted(referenced_files)
        ],
        "engine_files": [file_manifest(path) for path in engine_files],
    }


def task_fixture_contract(task: TaskSpec) -> dict[str, Any]:
    revision = _git_text(task.fixture.repository, "rev-parse", task.fixture.revision)
    return {
        "repository": str(task.fixture.repository),
        "requested_revision": task.fixture.revision,
        "resolved_revision": revision.strip(),
        "submodules": task.fixture.submodules,
    }


def changed_paths_manifest(
    changed_paths: list[str],
    *,
    workspace: Path,
) -> dict[str, Any]:
    normalized = sorted(changed_paths)
    content = ("\n".join(normalized) + ("\n" if normalized else "")).encode("utf-8")
    return {
        "count": len(normalized),
        "sha256": hashlib.sha256(content).hexdigest(),
        "entries": [
            _workspace_entry(workspace, relative_path)
            for relative_path in normalized
        ],
    }


def runner_execution_contract(runner: RunnerSpec) -> dict[str, Any]:
    provider_contract = _provider_contract(runner.provider_id)
    common = {
        "schema_version": 1,
        "node_type": runner.node_type,
        "provider_id": runner.provider_id,
        "provider_configuration": provider_contract,
        "benchmark_engine": file_manifest(
            PROJECT_ROOT / "scripts" / "benchmark_long_task.py"
        ),
    }
    if runner.node_type == "codex":
        return {
            **common,
            "runtime": {
                "reasoning_effort": "high",
                "sandbox": "danger-full-access",
                "web_search": "live",
            },
        }
    profile_path = resolve_agent_profile(runner.profile, project_root=PROJECT_ROOT)
    profile = _read_json_object(profile_path)
    fields = profile.get("fields")
    config = dict(fields) if isinstance(fields, dict) else dict(profile)
    profile_ab_comparison = profile_ab_comparison_contract(profile)
    if (
        profile_ab_comparison is not None
        and profile_ab_comparison["provider_id"] != runner.provider_id
    ):
        raise ValueError(
            f"Curated Profile {profile_ab_comparison['profile_id']!r} declares Provider "
            f"{profile_ab_comparison['provider_id']!r}, but runner {runner.runner_id!r} "
            f"selects {runner.provider_id!r}."
        )
    return {
        **common,
        "profile": file_manifest(profile_path),
        "profile_ab_comparison": profile_ab_comparison,
        "runtime_configuration": {
            key: config.get(key)
            for key in (
                "collaboration_mode",
                "instruction",
                "mcp_servers",
                "plugins",
                "reasoning_effort",
                "reasoning_summary",
                "skills",
                "system_prompt",
                "thinking",
                "tools",
                "web_search",
            )
        },
    }


def validate_profile_ab_runner_contracts(contracts: list[dict[str, Any]]) -> None:
    experiments: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        comparison = contract.get("profile_ab_comparison")
        if not isinstance(comparison, dict):
            continue
        experiments.setdefault(str(comparison["experiment_id"]), []).append(comparison)
    for experiment_id, pair in experiments.items():
        if len(pair) == 1:
            continue
        if len(pair) != 2:
            raise ValueError(
                f"Profile A/B experiment {experiment_id!r} must contain exactly two runners."
            )
        variants = {item["variant"] for item in pair}
        hashes = {item["controlled_configuration_sha256"] for item in pair}
        providers = {item["provider_id"] for item in pair}
        profiles = {item["profile_id"] for item in pair}
        peers = {item["peer_profile_id"] for item in pair}
        if variants != {"A", "B"}:
            raise ValueError(f"Profile A/B experiment {experiment_id!r} must contain variants A and B.")
        if len(hashes) != 1:
            raise ValueError(
                f"Profile A/B experiment {experiment_id!r} changes controlled runtime fields."
            )
        if len(providers) != 2:
            raise ValueError(
                f"Profile A/B experiment {experiment_id!r} must compare two Provider IDs."
            )
        if profiles != peers:
            raise ValueError(
                f"Profile A/B experiment {experiment_id!r} peer references are not symmetric."
            )


def _command_contracts(
    commands: tuple[CommandSpec, ...],
    *,
    phase: str,
) -> list[dict[str, Any]]:
    return [
        {
            "phase": phase,
            "id": command.command_id,
            "argv": list(command.argv),
            "timeout_seconds": command.timeout_seconds,
            "required": command.required,
            "weight": command.weight,
            "referenced_files": _referenced_files(command),
        }
        for command in commands
    ]


def _referenced_files(command: CommandSpec) -> list[dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for argument in command.argv:
        candidate = Path(argument).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            manifest = file_manifest(candidate.resolve())
            files[manifest["path"]] = manifest
    return [files[path] for path in sorted(files)]


def _workspace_entry(workspace: Path, relative_path: str) -> dict[str, Any]:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe benchmark changed path: {relative_path!r}.")
    path = workspace.joinpath(*relative.parts)
    if path.is_symlink():
        target = str(path.readlink())
        return {
            "path": relative_path,
            "kind": "symlink",
            "bytes": len(target.encode("utf-8")),
            "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        }
    if path.is_file():
        content = path.read_bytes()
        return {
            "path": relative_path,
            "kind": "file",
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    if path.is_dir():
        return {
            "path": relative_path,
            "kind": "directory",
            "bytes": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
    return {
        "path": relative_path,
        "kind": "deleted",
        "bytes": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }


def _git_text(repository: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repository), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Failed to resolve benchmark fixture revision: {detail}")
    return process.stdout.decode("utf-8", errors="strict")


def _provider_contract(provider_id: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "config" / "modelProvider.json"
    payload = _read_json_object(path)
    providers = payload.get("providers")
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise ValueError(f"Benchmark provider does not exist: {provider_id!r}.")
    return {
        "path": str(path),
        "provider_id": provider_id,
        "sha256": _json_sha256(provider),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}.")
    return value


def _json_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_manifest(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


__all__ = [
    "changed_paths_manifest",
    "file_manifest",
    "runner_execution_contract",
    "task_evaluation_contract",
    "task_fixture_contract",
    "task_input_contract",
    "validate_profile_ab_runner_contracts",
]
