from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analysis_report import AnalysisReportContractError
from src.analysis_report import finalize_analysis_report
from src.analysis_verification_models import AnalysisVerificationContractError
from src.analysis_verification_models import parse_verification_gates
from src.analysis_verification_runner import run_analysis_verification
from src.task_direction_models import TaskDirectionContractError
from src.task_direction_store import TaskDirectionStore


class _Agent:
    def __init__(self, memory_path, task_id="analysis-task-1"):
        self.current_memory_path = str(memory_path)
        self._agentpark_task_id = task_id
        self.config = {}


def _direction_state(*, criterion_status="pending", evidence=None):
    evidence = evidence or []
    evidence_ids = [item["id"] for item in evidence]
    return {
        "objective": "Analyze the current repository.",
        "hypotheses": [],
        "evidence": evidence,
        "unresolved_risks": [],
        "done_criteria": [
            {
                "id": "d.analysis",
                "statement": "Complete and verify the analysis.",
                "status": criterion_status,
                "evidence_ids": evidence_ids if criterion_status == "met" else [],
            }
        ],
    }


def _gates():
    return {
        "security": [{"id": "security.scan", "command": "security", "timeout_seconds": 30}],
        "full_test": [{"id": "test.full", "command": "full-test", "timeout_seconds": 300}],
        "build": [{"id": "build.web", "command": "build", "timeout_seconds": 300}],
        "config_drift": [{"id": "config.diff", "command": "config-drift", "timeout_seconds": 30}],
    }


def _completion(*, revision=1, evidence=None, criteria=None):
    return {
        "expected_revision": revision,
        "evidence": evidence or [],
        "hypotheses": [],
        "risks": [],
        "criteria": criteria or [],
    }


def test_analysis_verification_requires_every_named_gate():
    gates = _gates()
    gates.pop("security")

    with pytest.raises(AnalysisVerificationContractError, match="missing required fields: security"):
        parse_verification_gates(gates)


def test_analysis_verification_executes_all_gates_and_preserves_failure(monkeypatch, tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    TaskDirectionStore.for_agent(agent).replace(expected_revision=0, state=_direction_state())
    observed = []

    def execute(command, **_kwargs):
        observed.append(command)
        if command == "full-test":
            return json.dumps(
                {"status": "error", "returncode": 1, "stdout": "42 failed", "stderr": ""}
            )
        stdout = "## main" if command == "git status --short --branch" else f"{command} ok"
        return json.dumps({"status": "success", "returncode": 0, "stdout": stdout, "stderr": ""})

    monkeypatch.setattr("src.analysis_verification_runner.execute_console_command", execute)
    result = run_analysis_verification(_gates(), agent=agent)

    assert result["quality_status"] == "findings_present"
    assert observed == ["security", "full-test", "build", "config-drift", "git status --short --branch"]
    statuses = {gate["name"]: gate["status"] for gate in result["gates"]}
    assert statuses == {
        "security": "passed",
        "full_test": "failed",
        "build": "passed",
        "config_drift": "passed",
        "worktree": "passed",
    }
    security_check = result["gates"][0]["checks"][0]
    assert "output_preview" not in security_check
    test_check = result["gates"][1]["checks"][0]
    assert "42 failed" in test_check["output_preview"]
    assert Path(result["artifact_path"]).is_file()


def test_analysis_verification_marks_dirty_worktree_as_finding(monkeypatch, tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    TaskDirectionStore.for_agent(agent).replace(expected_revision=0, state=_direction_state())

    def execute(command, **_kwargs):
        stdout = "## main\n M src/runtime.py\n?? TODO.md" if command.startswith("git status") else "ok"
        return json.dumps({"status": "success", "returncode": 0, "stdout": stdout, "stderr": ""})

    monkeypatch.setattr("src.analysis_verification_runner.execute_console_command", execute)
    result = run_analysis_verification(_gates(), agent=agent)

    assert result["quality_status"] == "findings_present"
    worktree = result["gates"][-1]
    assert worktree["name"] == "worktree"
    assert worktree["status"] == "failed"
    assert "M src/runtime.py" in worktree["checks"][0]["output_preview"]


def test_analysis_verification_rejects_success_status_with_nonzero_returncode(
    monkeypatch,
    tmp_path,
):
    agent = _Agent(tmp_path / "memory.md")
    TaskDirectionStore.for_agent(agent).replace(expected_revision=0, state=_direction_state())

    def execute(command, **_kwargs):
        if command == "full-test":
            return json.dumps(
                {
                    "status": "success",
                    "returncode": 1,
                    "stdout": "1 failed, 1523 passed",
                    "stderr": "",
                }
            )
        return json.dumps(
            {
                "status": "success",
                "returncode": 0,
                "stdout": "## main" if command.startswith("git status") else "ok",
                "stderr": "",
            }
        )

    monkeypatch.setattr("src.analysis_verification_runner.execute_console_command", execute)
    result = run_analysis_verification(_gates(), agent=agent)

    full_test = next(gate for gate in result["gates"] if gate["name"] == "full_test")
    assert full_test["status"] == "failed"
    assert full_test["checks"][0]["tool_status"] == "success"
    assert full_test["checks"][0]["returncode"] == 1
    assert "1 failed, 1523 passed" in full_test["checks"][0]["output_preview"]


def test_analysis_report_requires_completion_for_every_pending_criterion(monkeypatch, tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    TaskDirectionStore.for_agent(agent).replace(expected_revision=0, state=_direction_state())
    monkeypatch.setattr(
        "src.analysis_verification_runner.execute_console_command",
        lambda command, **_kwargs: json.dumps(
            {
                "status": "success",
                "returncode": 0,
                "stdout": "## main" if command.startswith("git status") else command,
                "stderr": "",
            }
        ),
    )
    verification = run_analysis_verification(_gates(), agent=agent)

    with pytest.raises(TaskDirectionContractError, match="must resolve every pending criterion"):
        finalize_analysis_report(
            title="Architecture report",
            conclusion="The architecture has an explicit runtime boundary.",
            decisive_evidence=[
                {"title": "Runtime", "finding": "Boundary exists.", "source": "src/runtime.py:1"}
            ],
            priorities=[
                {"severity": "P1", "action": "Split module.", "rationale": "It is oversized."}
            ],
            appendix_sections=[{"title": "Inventory", "content": "Detailed inventory."}],
            validation_run_id=verification["run_id"],
            direction_completion=_completion(),
            agent=agent,
        )


def test_analysis_report_writes_layered_main_and_appendix(monkeypatch, tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    evidence = [
        {
            "id": "e.verification",
            "kind": "test",
            "summary": "All verification gates ran.",
            "source": "analysis_verification.json",
        }
    ]
    store = TaskDirectionStore.for_agent(agent)
    store.replace(expected_revision=0, state=_direction_state())
    monkeypatch.setattr(
        "src.analysis_verification_runner.execute_console_command",
        lambda command, **_kwargs: json.dumps(
            {
                "status": "success",
                "returncode": 0,
                "stdout": "## main" if command.startswith("git status") else command,
                "stderr": "",
            }
        ),
    )
    verification = run_analysis_verification(_gates(), agent=agent)
    result = finalize_analysis_report(
        title="Architecture report",
        conclusion="The main report stays concise.",
        decisive_evidence=[
            {"title": "Runtime", "finding": "Boundary exists.", "source": "src/runtime.py:1"}
        ],
        priorities=[
            {"severity": "P1", "action": "Split module.", "rationale": "It is oversized."}
        ],
        appendix_sections=[
            {"title": "Inventory", "content": "A" * 5000},
            {"title": "Call chain", "content": "Detailed call chain."},
        ],
        validation_run_id=verification["run_id"],
        direction_completion=_completion(
            evidence=evidence,
            criteria=[
                {
                    "id": "d.analysis",
                    "status": "met",
                    "evidence_ids": ["e.verification"],
                }
            ],
        ),
        agent=agent,
    )

    main = Path(result["main_report_path"]).read_text(encoding="utf-8")
    appendix = Path(result["appendix_path"]).read_text(encoding="utf-8")
    assert "The main report stays concise." in main
    assert "A" * 1000 not in main
    assert "A" * 1000 in appendix
    assert result["appendix_chars"] > 5000
    assert result["task_direction_status"] == "completed"
    completed = TaskDirectionStore.for_agent(agent).read()
    assert completed.status == "completed"
    assert completed.revision == 2
    assert completed.state.evidence[0].id == "e.verification"
    assert completed.state.done_criteria[0].status == "met"


def test_analysis_report_mismatch_returns_exact_expected_validation_run_id(monkeypatch, tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    evidence = [
        {
            "id": "e.verification",
            "kind": "test",
            "summary": "All verification gates ran.",
            "source": "analysis_verification.json",
        }
    ]
    store = TaskDirectionStore.for_agent(agent)
    store.replace(expected_revision=0, state=_direction_state())
    monkeypatch.setattr(
        "src.analysis_report.load_analysis_verification",
        lambda _agent: {"run_id": "verification_exact_123"},
    )

    with pytest.raises(
        AnalysisReportContractError,
        match="expected='verification_exact_123'",
    ):
        finalize_analysis_report(
            title="Architecture report",
            conclusion="The main report stays concise.",
            decisive_evidence=[
                {"title": "Runtime", "finding": "Boundary exists.", "source": "src/runtime.py:1"}
            ],
            priorities=[
                {"severity": "P1", "action": "Split module.", "rationale": "It is oversized."}
            ],
            appendix_sections=[{"title": "Inventory", "content": "Detailed inventory."}],
            validation_run_id="verification_exact_12",
            direction_completion=_completion(
                evidence=evidence,
                criteria=[
                    {
                        "id": "d.analysis",
                        "status": "met",
                        "evidence_ids": ["e.verification"],
                    }
                ],
            ),
            agent=agent,
        )
    assert store.read().status == "active"
