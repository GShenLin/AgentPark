from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from typing import Any

from src.analysis_verification_runner import load_analysis_verification
from src.file_transaction import atomic_write_text
from src.task_direction_completion import TaskDirectionCompletion
from src.task_direction_store import TaskDirectionStore


ANALYSIS_REPORT_SCHEMA_VERSION = 1
ANALYSIS_REPORT_MAIN_FILENAME = "analysis_report.md"
ANALYSIS_REPORT_APPENDIX_FILENAME = "analysis_report_appendix.md"
MAX_CONCLUSION_CHARS = 4_000
MAX_EVIDENCE_ITEMS = 15
MAX_PRIORITY_ITEMS = 15
MAX_APPENDIX_SECTIONS = 30
MAX_APPENDIX_SECTION_CHARS = 30_000
MAX_APPENDIX_TOTAL_CHARS = 500_000


class AnalysisReportContractError(ValueError):
    """Raised when a layered analysis report violates its delivery contract."""


@dataclass(frozen=True)
class ReportEvidence:
    title: str
    finding: str
    source: str


@dataclass(frozen=True)
class ReportPriority:
    severity: str
    action: str
    rationale: str


@dataclass(frozen=True)
class AppendixSection:
    title: str
    content: str


def finalize_analysis_report(
    *,
    title: object,
    conclusion: object,
    decisive_evidence: object,
    priorities: object,
    appendix_sections: object,
    validation_run_id: object,
    direction_completion: object,
    agent: object,
) -> dict[str, Any]:
    resolved_title = _text(title, "title", 200)
    resolved_conclusion = _text(conclusion, "conclusion", MAX_CONCLUSION_CHARS)
    evidence = _parse_evidence(decisive_evidence)
    priority_items = _parse_priorities(priorities)
    appendix = _parse_appendix(appendix_sections)
    run_id = _text(validation_run_id, "validation_run_id", 100)

    direction_store = TaskDirectionStore.for_agent(agent)
    direction = direction_store.read()
    if direction is None:
        raise AnalysisReportContractError("final report requires an initialized task direction state")
    completion = TaskDirectionCompletion.from_payload(
        direction_completion,
        current_state=direction.state,
    )
    if completion.expected_revision != direction.revision:
        raise AnalysisReportContractError(
            "direction_completion.expected_revision does not match the current task direction: "
            f"supplied={completion.expected_revision}, expected={direction.revision}"
        )
    validation = load_analysis_verification(agent)
    expected_run_id = str(validation.get("run_id") or "")
    if expected_run_id != run_id:
        raise AnalysisReportContractError(
            "validation_run_id does not match the latest analysis verification artifact: "
            f"supplied={run_id!r}, expected={expected_run_id!r}. "
            "Retry with the exact expected validation_run_id."
        )

    output_dir = os.path.dirname(direction_store.path)
    appendix_path = os.path.join(output_dir, ANALYSIS_REPORT_APPENDIX_FILENAME)
    main_path = os.path.join(output_dir, ANALYSIS_REPORT_MAIN_FILENAME)
    appendix_markdown = _render_appendix(resolved_title, appendix)
    main_markdown = _render_main(
        title=resolved_title,
        conclusion=resolved_conclusion,
        evidence=evidence,
        priorities=priority_items,
        validation=validation,
        appendix_path=appendix_path,
    )
    atomic_write_text(appendix_path, appendix_markdown, encoding="utf-8")
    atomic_write_text(main_path, main_markdown, encoding="utf-8")
    completed_direction = direction_store.complete_with_state(
        expected_revision=completion.expected_revision,
        state=completion.state.to_payload(),
    )
    return {
        "status": "success",
        "schema_version": ANALYSIS_REPORT_SCHEMA_VERSION,
        "main_report_path": main_path,
        "appendix_path": appendix_path,
        "main_markdown": main_markdown,
        "appendix_chars": len(appendix_markdown),
        "validation_run_id": run_id,
        "task_direction_status": completed_direction.status,
    }


def _parse_evidence(value: object) -> tuple[ReportEvidence, ...]:
    items = _bounded_items(value, "decisive_evidence", MAX_EVIDENCE_ITEMS, require_non_empty=True)
    output = []
    for index, item in enumerate(items):
        label = f"decisive_evidence[{index}]"
        payload = _strict_object(item, label, {"title", "finding", "source"})
        output.append(
            ReportEvidence(
                title=_text(payload.get("title"), f"{label}.title", 300),
                finding=_text(payload.get("finding"), f"{label}.finding", 3_000),
                source=_text(payload.get("source"), f"{label}.source", 2_000),
            )
        )
    return tuple(output)


def _parse_priorities(value: object) -> tuple[ReportPriority, ...]:
    items = _bounded_items(value, "priorities", MAX_PRIORITY_ITEMS, require_non_empty=True)
    output = []
    for index, item in enumerate(items):
        label = f"priorities[{index}]"
        payload = _strict_object(item, label, {"severity", "action", "rationale"})
        severity = str(payload.get("severity") or "").strip()
        if severity not in {"P0", "P1", "P2", "P3"}:
            raise AnalysisReportContractError(f"{label}.severity must be one of P0, P1, P2, P3")
        output.append(
            ReportPriority(
                severity=severity,
                action=_text(payload.get("action"), f"{label}.action", 2_000),
                rationale=_text(payload.get("rationale"), f"{label}.rationale", 2_000),
            )
        )
    return tuple(output)


def _parse_appendix(value: object) -> tuple[AppendixSection, ...]:
    items = _bounded_items(value, "appendix_sections", MAX_APPENDIX_SECTIONS, require_non_empty=True)
    output = []
    total_chars = 0
    for index, item in enumerate(items):
        label = f"appendix_sections[{index}]"
        payload = _strict_object(item, label, {"title", "content"})
        content = _text(payload.get("content"), f"{label}.content", MAX_APPENDIX_SECTION_CHARS)
        total_chars += len(content)
        output.append(
            AppendixSection(
                title=_text(payload.get("title"), f"{label}.title", 300),
                content=content,
            )
        )
    if total_chars > MAX_APPENDIX_TOTAL_CHARS:
        raise AnalysisReportContractError(
            f"appendix section content cannot exceed {MAX_APPENDIX_TOTAL_CHARS} total characters"
        )
    return tuple(output)


def _render_main(
    *,
    title: str,
    conclusion: str,
    evidence: tuple[ReportEvidence, ...],
    priorities: tuple[ReportPriority, ...],
    validation: dict[str, Any],
    appendix_path: str,
) -> str:
    lines = [f"# {title}", "", conclusion, "", "## Decisive evidence", ""]
    lines.extend(
        f"- **{item.title}** — {item.finding} Source: `{item.source}`"
        for item in evidence
    )
    lines.extend(["", "## Priorities", ""])
    lines.extend(
        f"- **{item.severity}** {item.action} — {item.rationale}"
        for item in priorities
    )
    lines.extend(["", "## Verification", ""])
    for gate in validation.get("gates") or []:
        checks = ", ".join(
            f"{check.get('id')}={check.get('status')}"
            for check in gate.get("checks") or []
        )
        lines.append(f"- **{gate.get('name')}**: {gate.get('status')} ({checks})")
    lines.extend(
        [
            "",
            f"Full inventory and detailed notes: `{appendix_path}`",
            "",
            f"Generated at {datetime.now().astimezone().isoformat()}.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_appendix(title: str, sections: tuple[AppendixSection, ...]) -> str:
    lines = [f"# {title} — Appendix", ""]
    for section in sections:
        lines.extend([f"## {section.title}", "", section.content, ""])
    return "\n".join(lines)


def _bounded_items(value: object, field: str, limit: int, *, require_non_empty: bool) -> list[Any]:
    if not isinstance(value, list):
        raise AnalysisReportContractError(f"{field} must be an array")
    if require_non_empty and not value:
        raise AnalysisReportContractError(f"{field} must be a non-empty array")
    if len(value) > limit:
        raise AnalysisReportContractError(f"{field} cannot contain more than {limit} items")
    return value


def _strict_object(value: object, label: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AnalysisReportContractError(f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AnalysisReportContractError(f"{label} has unknown fields: {', '.join(unknown)}")
    return value


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisReportContractError(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text) > limit:
        raise AnalysisReportContractError(f"{field} cannot exceed {limit} characters")
    return text
