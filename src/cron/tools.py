"""Skill operations use trusted runtime identity, never model-supplied node paths."""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.providers.agent_runtime_context import get_agent_runtime_context
from .repository import CronRepository
from .schedule import CreateJob, DeleteJob, UpdateJob


def _scope(agent):
    context = get_agent_runtime_context(agent)
    if not context.node_id or not context.graph_id or not context.node_directory:
        raise ValueError("Cron requires an AgentPark node runtime")
    node = Path(context.node_directory).resolve()
    if node.name != context.node_id or node.parent.name != context.graph_id:
        raise ValueError("Cron runtime identity does not match its node directory")
    config = json.loads((node / "config.json").read_text(encoding="utf-8"))
    if config.get("type_id") != "agent_node":
        raise ValueError("Cron requires an agent_node target")
    if context.remote_enabled:
        raise ValueError("Cron currently requires execution on the host owning the node; remote workers are unsupported")
    if context.access_role not in {"developer", "nondeveloper"}:
        raise ValueError("Cron requires a trusted runtime access role")
    return CronRepository(node.parent), context


def cron_create(name, prompt, schedule, agent=None):
    spec = CreateJob.model_validate({"name": name, "prompt": prompt, "schedule": schedule})
    repo, ctx = _scope(agent)
    return json.dumps({"job": repo.create(ctx.node_id, spec, ctx.access_role, time.time())}, ensure_ascii=False)


def cron_list(agent=None):
    repo, ctx = _scope(agent)
    return json.dumps(repo.list(ctx.node_id), ensure_ascii=False)


def cron_update(job_id, expected_revision, changes, agent=None):
    if not isinstance(changes, dict) or set(changes) - {"name", "prompt", "schedule", "enabled"}:
        raise ValueError("changes may contain only name, prompt, schedule, enabled")
    spec = UpdateJob.model_validate({"job_id": job_id, "expected_revision": expected_revision, **changes})
    repo, ctx = _scope(agent)
    return json.dumps({"job": repo.update(ctx.node_id, spec, ctx.access_role, time.time())}, ensure_ascii=False)


def cron_delete(job_id, expected_revision, agent=None):
    spec = DeleteJob.model_validate({"job_id": job_id, "expected_revision": expected_revision})
    repo, ctx = _scope(agent)
    repo.delete(ctx.node_id, spec.job_id, spec.expected_revision, time.time())
    return json.dumps({"deleted": spec.job_id, "running_actions_are_not_interrupted": True})
