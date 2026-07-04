from __future__ import annotations

from typing import Any

from src.providers.agent_runtime_context import get_agent_runtime_context


COLLABORATION_MODE_TEXT_PREFIX = "<collaboration_mode>"
COLLABORATION_MODE_TEXT_SUFFIX = "</collaboration_mode>"
DEFAULT_COLLABORATION_MODE = "default"
PLAN_COLLABORATION_MODE = "plan"


def resolve_agent_collaboration_mode(agent: object = None, config: dict[str, Any] | None = None) -> str:
    runtime_context = get_agent_runtime_context(agent)
    value = _first_value(
        runtime_context.collaboration_mode,
        (config or {}).get("collaborationMode") if isinstance(config, dict) else None,
        (config or {}).get("collaboration_mode") if isinstance(config, dict) else None,
    )
    text = str(value or "").strip().lower()
    if text == PLAN_COLLABORATION_MODE:
        return PLAN_COLLABORATION_MODE
    return DEFAULT_COLLABORATION_MODE


def collaboration_mode_context(agent: object = None, config: dict[str, Any] | None = None) -> dict[str, str]:
    return {"mode": resolve_agent_collaboration_mode(agent, config)}


def format_collaboration_mode_instructions(mode: object) -> str:
    normalized = resolve_agent_collaboration_mode(config={"collaboration_mode": mode})
    if normalized == PLAN_COLLABORATION_MODE:
        body = PLAN_MODE_DEVELOPER_INSTRUCTIONS
    else:
        return ""
    return f"{COLLABORATION_MODE_TEXT_PREFIX}\n{body.strip()}\n{COLLABORATION_MODE_TEXT_SUFFIX}"


def is_collaboration_mode_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith(COLLABORATION_MODE_TEXT_PREFIX) and text.endswith(COLLABORATION_MODE_TEXT_SUFFIX)


def _first_value(*values: object) -> object:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return ""


PLAN_MODE_DEVELOPER_INSTRUCTIONS = """
# Plan Mode

You are in Plan Mode. Treat user requests as requests to plan the execution, not to perform it.

Mode rules:
- Ground yourself in the actual environment before asking questions.
- You may read files, search the repo, inspect configs, and run non-mutating checks that refine the plan.
- Do not edit files, apply patches, run migrations, or perform side-effectful implementation steps.
- Ask only for decisions that cannot be discovered from the environment and materially affect the plan.
- When the plan is decision complete, return exactly one `<proposed_plan>` block.
- The plan must include the goal, key implementation changes, tests, and assumptions.
""".strip()
