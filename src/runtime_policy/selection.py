from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.runtime_policy.contracts import _identifier, _strict_object


@dataclass(frozen=True)
class RuntimePolicySelection:
    policy_id: str | None
    overrides: dict[str, Any]

    @classmethod
    def from_profile_value(cls, payload: object) -> "RuntimePolicySelection":
        if payload is None or payload == "":
            return cls(policy_id=None, overrides={})
        data = _strict_object(
            payload,
            field="agent_profile.runtime_policy",
            required=set(),
            optional={"policy_id", "overrides"},
        )
        raw_policy_id = data.get("policy_id")
        policy_id = (
            _identifier(raw_policy_id, field="agent_profile.runtime_policy.policy_id")
            if raw_policy_id is not None
            else None
        )
        overrides = _strict_object(
            data.get("overrides", {}),
            field="agent_profile.runtime_policy.overrides",
            required=set(),
            optional={
                "task_direction",
                "completion_review",
                "implementation_checkpoint",
                "context_compaction",
            },
        )
        _validate_override_sections(overrides)
        return cls(policy_id=policy_id, overrides=overrides)


def _validate_override_sections(overrides: dict[str, Any]) -> None:
    allowed = {
        "task_direction": {
            "enabled",
            "required_tools",
            "analysis_tools",
            "core_prompt",
            "code_prompt",
        },
        "completion_review": {
            "enabled",
            "passes",
            "require_tool_executions",
            "require_done_criteria",
            "require_resolved_risks",
            "prompt",
        },
        "implementation_checkpoint": {
            "enabled",
            "evidence_operation_limit",
            "workspace_tool",
            "direct_evidence_tools",
            "workspace_evidence_kinds",
            "patch_tools",
            "workspace_patch_kinds",
            "prompt",
        },
        "context_compaction": {
            "enabled",
            "every_tool_calls",
            "input_tokens",
            "current_input_tokens",
            "output_tokens",
            "context_percent",
            "max_candidate_chars",
            "gate_prompt",
            "retry_prompt",
        },
    }
    for section, payload in overrides.items():
        _strict_object(
            payload,
            field=f"agent_profile.runtime_policy.overrides.{section}",
            required=set(),
            optional=allowed[section],
        )


__all__ = ["RuntimePolicySelection"]
