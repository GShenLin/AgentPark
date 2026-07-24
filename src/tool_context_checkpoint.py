from __future__ import annotations

import json
from typing import Any


CHECKPOINT_ARRAY_FIELDS = (
    "completed_facts",
    "changed_state",
    "verification",
    "failed_attempts",
    "remaining_steps",
    "avoid_repeating",
)
CHECKPOINT_STRING_FIELDS = ("task_anchor", "immediate_next_step")
CHECKPOINT_FIELDS = frozenset((*CHECKPOINT_STRING_FIELDS, *CHECKPOINT_ARRAY_FIELDS))


def normalize_tool_context_checkpoint(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("summary must be a structured checkpoint object")

    supplied = set(value)
    missing = sorted(CHECKPOINT_FIELDS - supplied)
    unknown = sorted(supplied - CHECKPOINT_FIELDS)
    if missing or unknown:
        raise ValueError(
            "summary checkpoint fields do not match the contract. "
            f"Missing: {missing}. Unknown: {unknown}. "
            f"Expected: {sorted(CHECKPOINT_FIELDS)}."
        )

    normalized: dict[str, Any] = {}
    for field in CHECKPOINT_STRING_FIELDS:
        text = str(value.get(field) or "").strip()
        if not text:
            raise ValueError(f"summary.{field} must be a non-empty string")
        normalized[field] = text

    for field in CHECKPOINT_ARRAY_FIELDS:
        items = value.get(field)
        if not isinstance(items, list):
            raise TypeError(f"summary.{field} must be an array of non-empty strings")
        normalized_items: list[str] = []
        for index, item in enumerate(items):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"summary.{field}[{index}] must be a non-empty string"
                )
            normalized_items.append(item.strip())
        normalized[field] = normalized_items

    if not normalized["remaining_steps"]:
        raise ValueError(
            "summary.remaining_steps must contain at least one pending step; "
            "return the final answer instead of compacting when no work remains"
        )
    if normalized["immediate_next_step"] not in normalized["remaining_steps"]:
        raise ValueError(
            "summary.immediate_next_step must exactly match one item in "
            "summary.remaining_steps"
        )
    return normalized


def render_tool_context_checkpoint(value: object) -> str:
    checkpoint = normalize_tool_context_checkpoint(value)
    return json.dumps(checkpoint, ensure_ascii=False, indent=2)


__all__ = [
    "CHECKPOINT_ARRAY_FIELDS",
    "CHECKPOINT_FIELDS",
    "CHECKPOINT_STRING_FIELDS",
    "normalize_tool_context_checkpoint",
    "render_tool_context_checkpoint",
]
