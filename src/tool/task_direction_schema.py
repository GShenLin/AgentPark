from __future__ import annotations


ID_SCHEMA = {
    "type": "string",
    "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$",
}
EVIDENCE_IDS_SCHEMA = {
    "type": "array",
    "items": ID_SCHEMA,
    "maxItems": 100,
}

HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "id": ID_SCHEMA,
        "statement": {"type": "string"},
        "status": {"type": "string", "enum": ["open", "confirmed", "rejected"]},
        "evidence_ids": EVIDENCE_IDS_SCHEMA,
    },
    "required": ["id", "statement", "status", "evidence_ids"],
    "additionalProperties": False,
}

EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": ID_SCHEMA,
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
}

RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": ID_SCHEMA,
        "severity": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
        "statement": {"type": "string"},
        "status": {"type": "string", "enum": ["open", "resolved"]},
        "evidence_ids": EVIDENCE_IDS_SCHEMA,
    },
    "required": ["id", "severity", "statement", "status", "evidence_ids"],
    "additionalProperties": False,
}

CRITERION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": ID_SCHEMA,
        "statement": {"type": "string"},
        "status": {"type": "string", "enum": ["pending", "met", "blocked"]},
        "evidence_ids": EVIDENCE_IDS_SCHEMA,
    },
    "required": ["id", "statement", "status", "evidence_ids"],
    "additionalProperties": False,
}

STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "hypotheses": {"type": "array", "items": HYPOTHESIS_SCHEMA, "maxItems": 50},
        "evidence": {"type": "array", "items": EVIDENCE_SCHEMA, "maxItems": 100},
        "unresolved_risks": {"type": "array", "items": RISK_SCHEMA, "maxItems": 50},
        "done_criteria": {
            "type": "array",
            "items": CRITERION_SCHEMA,
            "minItems": 1,
            "maxItems": 50,
        },
    },
    "required": [
        "objective",
        "hypotheses",
        "evidence",
        "unresolved_risks",
        "done_criteria",
    ],
    "additionalProperties": False,
}

UPDATE_PROPERTIES = {
    "expected_revision": {"type": "integer", "minimum": 1},
    "evidence": {"type": "array", "items": EVIDENCE_SCHEMA, "maxItems": 100},
    "hypotheses": {"type": "array", "items": HYPOTHESIS_SCHEMA, "maxItems": 50},
    "risks": {"type": "array", "items": RISK_SCHEMA, "maxItems": 50},
    "criteria": {"type": "array", "items": CRITERION_SCHEMA, "maxItems": 50},
}
UPDATE_REQUIRED = [
    "expected_revision",
    "evidence",
    "hypotheses",
    "risks",
    "criteria",
]
