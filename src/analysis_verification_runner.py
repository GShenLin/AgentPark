from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
import time
from typing import Any
import uuid

from functions.console_tools import execute_console_command
from src.analysis_verification_models import VerificationCheck
from src.analysis_verification_models import VerificationGate
from src.analysis_verification_models import parse_verification_gates
from src.file_transaction import atomic_write_text
from src.runtime_cancellation import cancel_source_from_agent
from src.runtime_cancellation import raise_if_cancel_requested
from src.task_direction_store import TaskDirectionStore


ANALYSIS_VERIFICATION_FILENAME = "analysis_verification.json"
ANALYSIS_VERIFICATION_SCHEMA_VERSION = 1
PREVIEW_GATES = {"full_test", "build", "worktree"}
MAX_PREVIEW_CHARS = 2400


def run_analysis_verification(gates: object, *, agent: object) -> dict[str, Any]:
    parsed_gates = parse_verification_gates(gates)
    _require_task_direction(agent)
    run_id = f"verification_{uuid.uuid4().hex}"
    started_at = datetime.now().astimezone().isoformat()
    started = time.monotonic()
    gate_results = [_execute_gate(gate, agent) for gate in parsed_gates]
    worktree_gate = VerificationGate(
        name="worktree",
        checks=(
            VerificationCheck(
                check_id="builtin.worktree_status",
                command="git status --short --branch",
                timeout_seconds=60,
            ),
        ),
    )
    gate_results.append(_execute_gate(worktree_gate, agent))
    report = {
        "schema_version": ANALYSIS_VERIFICATION_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "completed",
        "quality_status": (
            "passed"
            if all(gate["status"] == "passed" for gate in gate_results)
            else "findings_present"
        ),
        "started_at": started_at,
        "completed_at": datetime.now().astimezone().isoformat(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "gates": gate_results,
    }
    path = analysis_verification_path(agent)
    atomic_write_text(
        path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "success",
        "run_id": run_id,
        "quality_status": report["quality_status"],
        "artifact_path": path,
        "gates": [_gate_summary(gate) for gate in gate_results],
    }


def load_analysis_verification(agent: object) -> dict[str, Any]:
    path = analysis_verification_path(agent)
    if not os.path.isfile(path):
        raise FileNotFoundError("analysis verification artifact does not exist")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("analysis verification artifact must contain an object")
    if payload.get("schema_version") != ANALYSIS_VERIFICATION_SCHEMA_VERSION:
        raise ValueError("analysis verification artifact has an unsupported schema_version")
    return payload


def analysis_verification_path(agent: object) -> str:
    direction_store = TaskDirectionStore.for_agent(agent)
    return os.path.join(os.path.dirname(direction_store.path), ANALYSIS_VERIFICATION_FILENAME)


def _require_task_direction(agent: object) -> None:
    if TaskDirectionStore.for_agent(agent).read() is None:
        raise ValueError("analysis verification requires an initialized task direction state")


def _execute_gate(gate: VerificationGate, agent: object) -> dict[str, Any]:
    results = [_execute_check(gate.name, check, agent) for check in gate.checks]
    return {
        "name": gate.name,
        "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
        "checks": results,
    }


def _execute_check(gate_name: str, check: VerificationCheck, agent: object) -> dict[str, Any]:
    raise_if_cancel_requested(cancel_source_from_agent(agent))
    started = time.monotonic()
    raw_result = execute_console_command(
        command=check.command,
        timeout_seconds=check.timeout_seconds,
        agent=agent,
    )
    result = _decode_result(raw_result)
    status = str(result.get("status") or "").strip().lower()
    returncode = result.get("returncode")
    passed = (
        status in {"success", "completed", "ok"}
        and not isinstance(returncode, bool)
        and isinstance(returncode, int)
        and returncode == 0
    )
    if gate_name == "worktree" and passed:
        passed = _worktree_is_clean(str(result.get("stdout") or ""))
    output_text = "\n".join(
        str(result.get(key) or "") for key in ("stdout", "stderr", "error")
    ).strip()
    payload = {
        "id": check.check_id,
        "command": check.command,
        "status": "passed" if passed else "failed",
        "tool_status": status,
        "returncode": returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "output_chars": len(output_text),
        "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest()[:16],
        "result": result,
    }
    if gate_name in PREVIEW_GATES and output_text:
        payload["output_preview"] = output_text[-MAX_PREVIEW_CHARS:]
    return payload


def _worktree_is_clean(stdout: str) -> bool:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("##"):
        return False
    return len(lines) == 1


def _decode_result(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise TypeError(f"verification command returned unsupported type: {type(value).__name__}")
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise TypeError("verification command result must be a JSON object")
    return payload


def _gate_summary(gate: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for check in gate.get("checks") or []:
        checks.append(
            {
                key: check.get(key)
                for key in (
                    "id",
                    "status",
                    "tool_status",
                    "returncode",
                    "duration_ms",
                    "output_chars",
                    "output_sha256",
                    "output_preview",
                )
                if check.get(key) not in (None, "")
            }
        )
    return {"name": gate.get("name"), "status": gate.get("status"), "checks": checks}
