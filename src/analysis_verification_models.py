from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_ANALYSIS_GATES = ("security", "full_test", "build", "config_drift")
MAX_CHECKS_PER_GATE = 8
MAX_COMMAND_CHARS = 12_000


class AnalysisVerificationContractError(ValueError):
    """Raised when an analysis verification request violates its schema."""


@dataclass(frozen=True)
class VerificationCheck:
    check_id: str
    command: str
    timeout_seconds: int


@dataclass(frozen=True)
class VerificationGate:
    name: str
    checks: tuple[VerificationCheck, ...]


def parse_verification_gates(payload: object) -> tuple[VerificationGate, ...]:
    if not isinstance(payload, dict):
        raise AnalysisVerificationContractError("gates must be an object")
    unknown = sorted(set(payload) - set(REQUIRED_ANALYSIS_GATES))
    missing = sorted(set(REQUIRED_ANALYSIS_GATES) - set(payload))
    if unknown:
        raise AnalysisVerificationContractError(f"gates has unknown fields: {', '.join(unknown)}")
    if missing:
        raise AnalysisVerificationContractError(f"gates is missing required fields: {', '.join(missing)}")

    seen_ids: set[str] = set()
    gates = []
    for gate_name in REQUIRED_ANALYSIS_GATES:
        raw_checks = payload[gate_name]
        if not isinstance(raw_checks, list) or not raw_checks:
            raise AnalysisVerificationContractError(f"gates.{gate_name} must be a non-empty array")
        if len(raw_checks) > MAX_CHECKS_PER_GATE:
            raise AnalysisVerificationContractError(
                f"gates.{gate_name} cannot contain more than {MAX_CHECKS_PER_GATE} checks"
            )
        checks = tuple(
            _parse_check(raw_check, gate_name, index, seen_ids)
            for index, raw_check in enumerate(raw_checks)
        )
        gates.append(VerificationGate(name=gate_name, checks=checks))
    return tuple(gates)


def _parse_check(
    payload: object,
    gate_name: str,
    index: int,
    seen_ids: set[str],
) -> VerificationCheck:
    label = f"gates.{gate_name}[{index}]"
    if not isinstance(payload, dict):
        raise AnalysisVerificationContractError(f"{label} must be an object")
    unknown = sorted(set(payload) - {"id", "command", "timeout_seconds"})
    if unknown:
        raise AnalysisVerificationContractError(f"{label} has unknown fields: {', '.join(unknown)}")
    check_id = str(payload.get("id") or "").strip()
    if not check_id or len(check_id) > 80:
        raise AnalysisVerificationContractError(f"{label}.id must contain 1-80 characters")
    if check_id in seen_ids:
        raise AnalysisVerificationContractError(f"duplicate verification check id: {check_id}")
    seen_ids.add(check_id)
    command = payload.get("command")
    if not isinstance(command, str) or not command.strip():
        raise AnalysisVerificationContractError(f"{label}.command must be a non-empty string")
    command = command.strip()
    if len(command) > MAX_COMMAND_CHARS:
        raise AnalysisVerificationContractError(
            f"{label}.command cannot exceed {MAX_COMMAND_CHARS} characters"
        )
    timeout = payload.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
        raise AnalysisVerificationContractError(
            f"{label}.timeout_seconds must be an integer between 1 and 3600"
        )
    return VerificationCheck(check_id=check_id, command=command, timeout_seconds=timeout)
