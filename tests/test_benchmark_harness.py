from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.benchmark_harness_contract import HarnessSuite, HarnessValidationError
from scripts.benchmark_harness_evidence import (
    changed_paths_manifest,
    runner_execution_contract,
    task_evaluation_contract,
    task_fixture_contract,
    task_input_contract,
)
from scripts.benchmark_harness_imports import load_imported_runs
from scripts.benchmark_verification import git_changed_paths, verify_run
from scripts.benchmark_harness_report import build_suite_payload
from scripts.benchmark_harness_report import render_comparison_markdown


PROJECT_ROOT = Path(__file__).parents[1]


def _git(cwd: Path, *args: str) -> None:
    process = subprocess.run(
        ["git", "-C", str(cwd), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")


def _manifest(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "harness@example.test")
    _git(repository, "config", "user.name", "Harness Test")
    (repository / "target.txt").write_text("before\n", encoding="utf-8")
    _git(repository, "add", "target.txt")
    _git(repository, "commit", "-q", "-m", "fixture")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Change target.txt and run the verifier.\n", encoding="utf-8")
    (tmp_path / "acceptance.md").write_text(
        "target.txt must contain exactly after followed by a newline.\n",
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "fields": {
                    "provider_id": "GPT_Official",
                    "thinking": "enabled",
                    "reasoning_effort": "high",
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "harness.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_id": "contract-suite",
                "repetitions": 2,
                "tasks": [
                    {
                        "id": "edit-target",
                        "category": "coding",
                        "prompt_file": "prompt.md",
                        "source_session_id": "session-1",
                        "source_turn_id": "turn-1",
                        "oracle": {
                            "source": "independent-specification",
                            "reference": "test-contract-v1",
                            "acceptance_file": "acceptance.md",
                        },
                        "fixture": {
                            "repository": "repository",
                            "revision": "HEAD",
                        },
                        "verification": [
                            {
                                "id": "content",
                                "argv": [
                                    "python",
                                    "-c",
                                    "from pathlib import Path; assert Path('target.txt').read_text() == 'after\\n'",
                                ],
                                "timeout_seconds": 10,
                                "weight": 3,
                            }
                        ],
                        "required_changed_paths": ["target.txt"],
                        "forbidden_changed_paths": ["secrets/**"],
                    }
                ],
                "runners": [
                    {
                        "id": "agent",
                        "node_type": "agent",
                        "provider_id": "GPT_Official",
                        "profile": str(profile),
                    },
                    {
                        "id": "codex",
                        "node_type": "codex",
                        "provider_id": "GPT_Official",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_harness_contract_resolves_paths_and_requires_two_runners(tmp_path):
    manifest = _manifest(tmp_path)
    suite = HarnessSuite.load(manifest)

    assert suite.suite_id == "contract-suite"
    assert suite.repetitions == 2
    assert suite.tasks[0].fixture.repository == (tmp_path / "repository").resolve()
    assert suite.tasks[0].verification[0].weight == 3
    assert suite.tasks[0].source_turn_id == "turn-1"
    assert suite.tasks[0].oracle.source == "independent-specification"
    assert suite.tasks[0].oracle.acceptance_file.name == "acceptance.md"
    assert suite.runners[0].profile.endswith("profile.json")
    agent_runner_contract = runner_execution_contract(suite.runners[0])
    assert agent_runner_contract["runtime_configuration"]["thinking"] == "enabled"
    assert (
        agent_runner_contract["effective_runtime_policy"]["policy_id"]
        == "coding-default"
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["runners"] = payload["runners"][:1]
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HarnessValidationError, match="at least two runners"):
        HarnessSuite.load(manifest)


def test_verification_requires_commands_and_changed_path_gates(tmp_path):
    suite = HarnessSuite.load(_manifest(tmp_path))
    task = suite.tasks[0]
    workspace = task.fixture.repository
    (workspace / "target.txt").write_text("after\n", encoding="utf-8")

    passed = verify_run(
        task,
        workspace=workspace,
        run_dir=tmp_path / "passed",
        benchmark_status="completed",
    )

    assert passed["completed"] is True
    assert passed["completion_score"] == 100.0
    assert passed["path_gate_passed"] is True

    (workspace / "secrets").mkdir()
    (workspace / "secrets" / "token.txt").write_text("not-a-real-token", encoding="utf-8")
    failed = verify_run(
        task,
        workspace=workspace,
        run_dir=tmp_path / "failed",
        benchmark_status="completed",
    )

    assert failed["completed"] is False
    assert failed["completion_score"] == 100.0
    assert failed["path_gate_passed"] is False


def test_changed_path_capture_handles_rename_records(tmp_path):
    suite = HarnessSuite.load(_manifest(tmp_path))
    workspace = suite.tasks[0].fixture.repository

    (workspace / "target.txt").rename(workspace / "renamed target.txt")
    _git(workspace, "add", "-A")

    assert git_changed_paths(workspace) == ["renamed target.txt", "target.txt"]


def test_suite_selects_speed_winner_only_after_verified_completion(tmp_path):
    suite = HarnessSuite.load(_manifest(tmp_path))

    def run(runner_id: str, duration_ms: int, completed: bool):
        return {
            "task_id": "edit-target",
            "runner_id": runner_id,
            "verification": {
                "completed": completed,
                "completion_score": 100.0 if completed else 50.0,
            },
            "benchmark": {
                "result": {
                    "summary": {
                        "duration_ms": duration_ms,
                        "usage": {"total_tokens": 100},
                    }
                }
            },
        }

    payload = build_suite_payload(
        suite,
        [
            run("agent", 200, True),
            run("agent", 220, True),
            run("codex", 100, True),
            run("codex", 110, False),
        ],
    )

    decision = payload["decision"]["tasks"][0]
    assert decision["validated_winner"] == "agent"
    markdown = render_comparison_markdown(payload)
    assert "2/2" in markdown
    assert "1/2" in markdown
    assert "100% verified completion" in markdown


def test_imported_baseline_requires_identical_input_fixture_and_runner(tmp_path):
    suite = HarnessSuite.load(_manifest(tmp_path))
    task = suite.tasks[0]
    result_path = tmp_path / "baseline.json"
    run = {
        "case_id": "edit-target__codex__r1",
        "task_id": task.task_id,
        "runner_id": "codex",
        "node_type": "codex",
        "provider_id": "GPT_Official",
        "runner_contract": runner_execution_contract(suite.runners[1]),
        "input_contract": task_input_contract(task),
        "evaluation_contract": task_evaluation_contract(task),
        "fixture": {
            **task_fixture_contract(task),
            "workspace": str(task.fixture.repository),
        },
        "verification": {
            "completed": True,
            "completion_score": 100,
            "changed_paths": [],
        },
        "workspace_state": changed_paths_manifest(
            [],
            workspace=task.fixture.repository,
        ),
        "benchmark": {"result": {"summary": {"duration_ms": 100}}},
    }
    result_path.write_text(
        json.dumps({"runs": [run]}),
        encoding="utf-8",
    )

    imported = load_imported_runs(suite, [result_path])

    assert imported[0]["case_id"] == "edit-target__codex__r1"
    assert imported[0]["execution_source"]["kind"] == "imported"

    run["input_contract"]["prompt"]["sha256"] = "tampered"
    result_path.write_text(json.dumps({"runs": [run]}), encoding="utf-8")
    with pytest.raises(HarnessValidationError, match="input contract"):
        load_imported_runs(suite, [result_path])


def test_imported_baseline_rejects_changed_evaluator(tmp_path):
    suite = HarnessSuite.load(_manifest(tmp_path))
    task = suite.tasks[0]
    result_path = tmp_path / "baseline.json"
    run = {
        "case_id": "edit-target__codex__r1",
        "task_id": task.task_id,
        "runner_id": "codex",
        "node_type": "codex",
        "provider_id": "GPT_Official",
        "runner_contract": runner_execution_contract(suite.runners[1]),
        "input_contract": task_input_contract(task),
        "evaluation_contract": task_evaluation_contract(task),
        "fixture": {
            **task_fixture_contract(task),
            "workspace": str(task.fixture.repository),
        },
        "verification": {
            "completed": True,
            "completion_score": 100,
            "changed_paths": [],
        },
        "workspace_state": changed_paths_manifest(
            [],
            workspace=task.fixture.repository,
        ),
        "benchmark": {"result": {"summary": {"duration_ms": 100}}},
    }
    run["evaluation_contract"]["commands"][0]["weight"] = 999
    result_path.write_text(json.dumps({"runs": [run]}), encoding="utf-8")

    with pytest.raises(HarnessValidationError, match="evaluation contract"):
        load_imported_runs(suite, [result_path])


def test_imported_baseline_rejects_changed_workspace_content(tmp_path):
    suite = HarnessSuite.load(_manifest(tmp_path))
    task = suite.tasks[0]
    workspace = task.fixture.repository
    (workspace / "target.txt").write_text("after\n", encoding="utf-8")
    changed_paths = ["target.txt"]
    result_path = tmp_path / "baseline.json"
    run = {
        "case_id": "edit-target__codex__r1",
        "task_id": task.task_id,
        "runner_id": "codex",
        "node_type": "codex",
        "provider_id": "GPT_Official",
        "runner_contract": runner_execution_contract(suite.runners[1]),
        "input_contract": task_input_contract(task),
        "evaluation_contract": task_evaluation_contract(task),
        "fixture": {
            **task_fixture_contract(task),
            "workspace": str(workspace),
        },
        "verification": {
            "completed": True,
            "completion_score": 100,
            "changed_paths": changed_paths,
        },
        "workspace_state": changed_paths_manifest(
            changed_paths,
            workspace=workspace,
        ),
        "benchmark": {"result": {"summary": {"duration_ms": 100}}},
    }
    result_path.write_text(json.dumps({"runs": [run]}), encoding="utf-8")
    assert len(load_imported_runs(suite, [result_path])) == 1

    (workspace / "target.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(HarnessValidationError, match="artifact contract"):
        load_imported_runs(suite, [result_path])


def test_diagnostic_task_can_be_verified_by_required_output_patterns(tmp_path):
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    task_payload = payload["tasks"][0]
    task_payload.pop("verification")
    task_payload["required_changed_paths"] = []
    task_payload["output_checks"] = [
        {
            "id": "protocol-version",
            "pattern": r"protocol[_ ]version\s*:?\s*1",
            "weight": 2,
        },
        {
            "id": "secondary-404",
            "pattern": r"404.*secondary|secondary.*404",
        },
    ]
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    suite = HarnessSuite.load(manifest)

    verification = verify_run(
        suite.tasks[0],
        workspace=suite.tasks[0].fixture.repository,
        run_dir=tmp_path / "diagnostic",
        benchmark_status="completed",
        benchmark_output=(
            "The worker registered with protocol_version: 1. "
            "The later 404 is a secondary symptom."
        ),
    )

    assert verification["completed"] is True
    assert verification["completion_score"] == 100.0
    assert verification["required_output_checks_passed"] is True


def test_codex_session_sample_catalog_has_replayable_prompt_provenance():
    catalog_path = PROJECT_ROOT / "benchmarks" / "session_samples.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    samples = payload["samples"]

    assert payload["schema_version"] == 1
    assert len(samples) >= 5
    assert len({sample["id"] for sample in samples}) == len(samples)
    assert {
        "cross-module-state-transition",
        "diagnosis-with-runtime-evidence",
        "desktop-mobile-ui",
        "compiler-configuration-drift",
        "configuration-ownership-migration",
    }.issubset({sample["category"] for sample in samples})
    for sample in samples:
        assert sample["source_session_id"]
        assert sample["source_turn_id"]
        assert sample["codex_duration_ms"] > 0
        prompt_path = catalog_path.parent / sample["prompt_file"]
        assert prompt_path.read_text(encoding="utf-8").strip()
        acceptance = sample.get("acceptance_file")
        if acceptance is not None:
            assert (catalog_path.parent / acceptance).read_text(encoding="utf-8").strip()
