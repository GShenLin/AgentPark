from __future__ import annotations

import json

from src.analysis_report import finalize_analysis_report as _finalize_analysis_report


def finalize_analysis_report(
    title,
    conclusion,
    decisive_evidence,
    priorities,
    appendix_sections,
    validation_run_id,
    direction_completion,
    agent=None,
):
    result = _finalize_analysis_report(
        title=title,
        conclusion=conclusion,
        decisive_evidence=decisive_evidence,
        priorities=priorities,
        appendix_sections=appendix_sections,
        validation_run_id=validation_run_id,
        direction_completion=direction_completion,
        agent=agent,
    )
    return json.dumps(result, ensure_ascii=False)


finalize_analysis_report_declaration = {
    "type": "function",
    "function": {
        "name": "finalize_analysis_report",
        "description": (
            "Finalize a layered codebase analysis report and atomically complete the task direction ledger. "
            "direction_completion adds only new evidence and status changes, must resolve every pending "
            "criterion, and must use the current ledger revision. validation_run_id must match the latest "
            "five-gate verification. Returns a concise main report and writes exhaustive details separately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "conclusion": {"type": "string"},
                "decisive_evidence": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 15,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "finding": {"type": "string"},
                            "source": {"type": "string"},
                        },
                        "required": ["title", "finding", "source"],
                        "additionalProperties": False,
                    },
                },
                "priorities": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 15,
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                            "action": {"type": "string"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["severity", "action", "rationale"],
                        "additionalProperties": False,
                    },
                },
                "appendix_sections": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 30,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["title", "content"],
                        "additionalProperties": False,
                    },
                },
                "validation_run_id": {"type": "string"},
                "direction_completion": {
                    "type": "object",
                    "properties": {
                        "expected_revision": {"type": "integer", "minimum": 1},
                        "evidence": {
                            "type": "array",
                            "maxItems": 100,
                            "description": (
                                "Only new evidence absent from the current ledger. Every id must be fresh; "
                                "do not repeat existing evidence objects. Use [] when verification evidence "
                                "is already stored, and reference existing ids from status resolutions."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "source",
                                            "test",
                                            "build",
                                            "security",
                                            "config",
                                            "worktree",
                                            "runtime",
                                            "other",
                                        ],
                                    },
                                    "summary": {"type": "string"},
                                    "source": {"type": "string"},
                                },
                                "required": ["id", "kind", "summary", "source"],
                                "additionalProperties": False,
                            },
                        },
                        "hypotheses": {
                            "type": "array",
                            "maxItems": 50,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["confirmed", "rejected"],
                                    },
                                    "evidence_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["id", "status", "evidence_ids"],
                                "additionalProperties": False,
                            },
                        },
                        "risks": {
                            "type": "array",
                            "maxItems": 50,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "status": {"type": "string", "enum": ["resolved"]},
                                    "evidence_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["id", "status", "evidence_ids"],
                                "additionalProperties": False,
                            },
                        },
                        "criteria": {
                            "type": "array",
                            "maxItems": 50,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "status": {"type": "string", "enum": ["met", "blocked"]},
                                    "evidence_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["id", "status", "evidence_ids"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": [
                        "expected_revision",
                        "evidence",
                        "hypotheses",
                        "risks",
                        "criteria",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "title",
                "conclusion",
                "decisive_evidence",
                "priorities",
                "appendix_sections",
                "validation_run_id",
                "direction_completion",
            ],
            "additionalProperties": False,
        },
    },
}
