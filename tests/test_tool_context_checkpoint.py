from __future__ import annotations

import json

import pytest

from src.tool_context_checkpoint import normalize_tool_context_checkpoint
from src.tool_context_checkpoint import render_tool_context_checkpoint


def _checkpoint():
    return {
        "task_anchor": "Implement the requested change and preserve strict contracts.",
        "completed_facts": ["src/example.py was inspected."],
        "changed_state": ["src/example.py now validates input."],
        "verification": ["Focused tests: 4 passed."],
        "failed_attempts": [],
        "remaining_steps": ["Run the broader regression suite."],
        "immediate_next_step": "Run the broader regression suite.",
        "avoid_repeating": ["Do not re-read src/example.py before another edit."],
    }


def test_checkpoint_round_trip_preserves_explicit_ledger():
    checkpoint = _checkpoint()

    assert normalize_tool_context_checkpoint(checkpoint) == checkpoint
    assert json.loads(render_tool_context_checkpoint(checkpoint)) == checkpoint


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.pop("verification"), "Missing"),
        (lambda value: value.update({"extra": []}), "Unknown"),
        (
            lambda value: value.update({"completed_facts": "already done"}),
            "completed_facts must be an array",
        ),
        (
            lambda value: value.update({"remaining_steps": []}),
            "must contain at least one pending step",
        ),
        (
            lambda value: value.update({"immediate_next_step": "Different step"}),
            "must exactly match",
        ),
    ],
)
def test_checkpoint_rejects_contract_drift(mutation, match):
    checkpoint = _checkpoint()
    mutation(checkpoint)

    with pytest.raises((TypeError, ValueError), match=match):
        normalize_tool_context_checkpoint(checkpoint)
