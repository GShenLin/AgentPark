from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from src.runtime_policy.catalog import RuntimePolicyCatalog
from src.runtime_policy.contracts import CodingRuntimePolicy
from src.runtime_policy.selection import RuntimePolicySelection


@dataclass(frozen=True)
class ResolvedRuntimePolicy:
    policy: CodingRuntimePolicy
    manifest: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_payload(),
            "manifest": copy.deepcopy(self.manifest),
        }


def resolve_runtime_policy(
    profile_value: object,
    *,
    workspace_root: str | None = None,
    catalog: RuntimePolicyCatalog | None = None,
) -> ResolvedRuntimePolicy:
    selection = RuntimePolicySelection.from_profile_value(profile_value)
    resolved_catalog = catalog or RuntimePolicyCatalog.load(workspace_root)
    catalog_policy = resolved_catalog.get(selection.policy_id)
    payload = catalog_policy.policy.to_payload()
    _apply_overrides(payload, selection.overrides)
    policy = CodingRuntimePolicy.from_payload(payload)
    prompt_sources = dict(catalog_policy.prompt_sources)
    for section_name, section_payload in selection.overrides.items():
        for prompt_key in _prompt_keys(section_name):
            if prompt_key in section_payload:
                prompt_sources[f"{section_name}.{prompt_key}"] = "agent_profile.runtime_policy"
    effective_payload = policy.to_payload()
    manifest = {
        "schema_version": 1,
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "selection_source": (
            "agent_profile.runtime_policy"
            if selection.policy_id is not None or selection.overrides
            else "default"
        ),
        "catalog_source": catalog_policy.source_path,
        "effective_sha256": _sha256_json(effective_payload),
        "prompts": _prompt_manifest(policy, prompt_sources),
    }
    return ResolvedRuntimePolicy(policy=policy, manifest=manifest)


def bound_runtime_policy_for_agent(agent: object) -> ResolvedRuntimePolicy | None:
    existing = getattr(agent, "_agentpark_resolved_runtime_policy", None)
    if isinstance(existing, ResolvedRuntimePolicy):
        return existing
    from src.providers.agent_runtime_context import get_agent_runtime_context

    context = get_agent_runtime_context(agent)
    context_policy = getattr(context, "runtime_policy", None)
    if isinstance(context_policy, ResolvedRuntimePolicy):
        return context_policy
    return None


def runtime_policy_for_agent(agent: object) -> ResolvedRuntimePolicy:
    existing = bound_runtime_policy_for_agent(agent)
    if existing is not None:
        return existing
    resolved = resolve_runtime_policy(None)
    setattr(agent, "_agentpark_resolved_runtime_policy", resolved)
    return resolved


def _apply_overrides(payload: dict[str, Any], overrides: dict[str, Any]) -> None:
    for section, section_overrides in overrides.items():
        target = payload[section]
        for key, value in section_overrides.items():
            target[key] = copy.deepcopy(value)


def _prompt_keys(section: str) -> tuple[str, ...]:
    if section == "task_direction":
        return ("core_prompt", "code_prompt")
    if section == "context_compaction":
        return ("gate_prompt", "retry_prompt")
    return ("prompt",)


def _prompt_manifest(
    policy: CodingRuntimePolicy,
    sources: dict[str, str],
) -> list[dict[str, Any]]:
    prompt_values = {
        "task_direction.core_prompt": policy.task_direction.core_prompt,
        "task_direction.code_prompt": policy.task_direction.code_prompt,
        "completion_review.prompt": policy.completion_review.prompt,
        "implementation_checkpoint.prompt": policy.implementation_checkpoint.prompt,
        "context_compaction.gate_prompt": policy.context_compaction.gate_prompt,
        "context_compaction.retry_prompt": policy.context_compaction.retry_prompt,
    }
    return [
        {
            "layer": layer,
            "source": sources.get(layer, "runtime_policy"),
            "chars": len(prompt),
            "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        }
        for layer, prompt in prompt_values.items()
    ]


def _sha256_json(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedRuntimePolicy",
    "bound_runtime_policy_for_agent",
    "resolve_runtime_policy",
    "runtime_policy_for_agent",
]
