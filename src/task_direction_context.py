from __future__ import annotations

import json

from src.runtime_policy import ResolvedRuntimePolicy, runtime_policy_for_agent
from src.task_direction_store import TaskDirectionStore


TASK_DIRECTION_CONTEXT_PREFIX = '<agentpark_task_direction schema_version="2">'
TASK_DIRECTION_CONTEXT_SUFFIX = "</agentpark_task_direction>"


def inject_task_direction_context(
    agent: object,
    *,
    role: str,
    runtime_policy: ResolvedRuntimePolicy | None = None,
) -> None:
    resolved = runtime_policy or runtime_policy_for_agent(agent)
    policy = resolved.policy.task_direction
    if not policy.enabled:
        return
    function_map = getattr(getattr(agent, "tools", None), "function_map", None)
    required_tools = set(policy.required_tools)
    if not isinstance(function_map, dict) or not required_tools.issubset(function_map):
        return
    protocol_context = (
        policy.code_prompt
        if set(policy.analysis_tools).issubset(function_map)
        else policy.core_prompt
    )
    agent.Message(role, protocol_context, persist=False)
    stored = TaskDirectionStore.for_agent(agent).read()
    if stored is None:
        return
    context = (
        TASK_DIRECTION_CONTEXT_PREFIX
        + "\n"
        + json.dumps(stored.to_payload(), ensure_ascii=False, sort_keys=True)
        + "\n"
        + TASK_DIRECTION_CONTEXT_SUFFIX
    )
    agent.Message(role, context, persist=False)


__all__ = [
    "TASK_DIRECTION_CONTEXT_PREFIX",
    "TASK_DIRECTION_CONTEXT_SUFFIX",
    "inject_task_direction_context",
]
