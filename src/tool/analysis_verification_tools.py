from __future__ import annotations

import json

from src.analysis_verification_runner import run_analysis_verification as _run_analysis_verification


def run_analysis_verification(gates, agent=None):
    return json.dumps(_run_analysis_verification(gates, agent=agent), ensure_ascii=False)


_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "command": {"type": "string"},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
    },
    "required": ["id", "command", "timeout_seconds"],
    "additionalProperties": False,
}


run_analysis_verification_declaration = {
    "type": "function",
    "function": {
        "name": "run_analysis_verification",
        "description": (
            "Run and persist the mandatory codebase-analysis verification protocol. Explicit commands are "
            "required for security, full_test, build, and config_drift; worktree status is appended by the "
            "runtime after those gates. Every gate is executed even when earlier gates fail. Failures remain "
            "first-class findings and are never converted into passing defaults."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gates": {
                    "type": "object",
                    "properties": {
                        "security": {"type": "array", "minItems": 1, "maxItems": 8, "items": _CHECK_SCHEMA},
                        "full_test": {"type": "array", "minItems": 1, "maxItems": 8, "items": _CHECK_SCHEMA},
                        "build": {"type": "array", "minItems": 1, "maxItems": 8, "items": _CHECK_SCHEMA},
                        "config_drift": {"type": "array", "minItems": 1, "maxItems": 8, "items": _CHECK_SCHEMA},
                    },
                    "required": ["security", "full_test", "build", "config_drift"],
                    "additionalProperties": False,
                }
            },
            "required": ["gates"],
            "additionalProperties": False,
        },
    },
}


run_analysis_verification.tool_timeout_seconds = 0
