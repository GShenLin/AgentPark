from __future__ import annotations

import json

from src.task_direction_store import TaskDirectionStore
from src.tool.task_direction_schema import STATE_SCHEMA
from src.tool.task_direction_schema import UPDATE_PROPERTIES
from src.tool.task_direction_schema import UPDATE_REQUIRED


def get_task_direction(agent=None):
    store = TaskDirectionStore.for_agent(agent)
    current = store.read()
    return json.dumps(
        {
            "status": "success",
            "task_id": store.task_id,
            "task_direction": current.to_payload() if current else None,
        },
        ensure_ascii=False,
    )


def replace_task_direction(expected_revision, state, agent=None):
    store = TaskDirectionStore.for_agent(agent)
    stored = store.replace(
        expected_revision=expected_revision,
        state=state,
    )
    return json.dumps(
        {"status": "success", "task_id": store.task_id, "task_direction": stored.to_payload()},
        ensure_ascii=False,
    )


def update_task_direction(expected_revision, evidence, hypotheses, risks, criteria, agent=None):
    store = TaskDirectionStore.for_agent(agent)
    stored, applied = store.update(
        expected_revision=expected_revision,
        update={
            "evidence": evidence,
            "hypotheses": hypotheses,
            "risks": risks,
            "criteria": criteria,
        },
    )
    return json.dumps(
        {
            "status": "success",
            "task_id": store.task_id,
            "revision": stored.revision,
            **applied.receipt(),
        },
        ensure_ascii=False,
    )


get_task_direction_declaration = {
    "type": "function",
    "function": {
        "name": "get_task_direction",
        "description": (
            "Read the explicit task direction ledger scoped to the current task_id. Returns null before "
            "this task initializes its own ledger; state from other tasks is never returned."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}

replace_task_direction_declaration = {
    "type": "function",
    "function": {
        "name": "replace_task_direction",
        "description": (
            "Atomically initialize the full task direction ledger with expected_revision=0. This tool is "
            "creation-only: an active ledger must use update_task_direction so unchanged state is not "
            "resent. Confirmed/rejected hypotheses, resolved risks, and met criteria must reference "
            "evidence ids. Existing, stale, and completed ledgers are rejected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expected_revision": {"type": "integer", "minimum": 0},
                "state": STATE_SCHEMA,
            },
            "required": ["expected_revision", "state"],
            "additionalProperties": False,
        },
    },
}

update_task_direction_declaration = {
    "type": "function",
    "function": {
        "name": "update_task_direction",
        "description": (
            "Atomically append evidence and upsert only changed hypotheses, risks, or criteria in an "
            "initialized active task direction. This is the required compact path for intermediate "
            "progress: unchanged state is neither sent nor echoed. Existing statements/severities and "
            "terminal statuses are immutable; evidence ids are append-only; stale revisions fail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                **UPDATE_PROPERTIES,
            },
            "required": UPDATE_REQUIRED,
            "additionalProperties": False,
        },
    },
}
