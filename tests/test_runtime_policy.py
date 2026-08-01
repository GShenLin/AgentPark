from __future__ import annotations

import copy
import json

import pytest

from src.runtime_policy import RuntimePolicyCatalog, resolve_runtime_policy
from src.runtime_policy.contracts import RuntimePolicyValidationError


def test_default_policy_resolves_when_profile_value_is_missing():
    resolved = resolve_runtime_policy(None)

    assert resolved.policy.policy_id == "coding-default"
    assert resolved.policy.completion_review.enabled is False
    assert resolved.policy.completion_review.passes == 1
    assert resolved.policy.completion_review.require_done_criteria is False
    assert resolved.policy.completion_review.require_resolved_risks is False
    assert resolved.policy.implementation_checkpoint.evidence_operation_limit == 12
    assert resolved.policy.implementation_checkpoint.workspace_tool == "workspace_exec"
    assert resolved.policy.context_compaction.every_tool_calls == 30
    assert resolved.policy.context_compaction.current_input_tokens == 90000
    assert resolved.policy.context_compaction.context_percent == 0
    assert resolved.manifest["selection_source"] == "default"
    assert len(resolved.manifest["effective_sha256"]) == 64
    assert {item["layer"] for item in resolved.manifest["prompts"]} == {
        "task_direction.core_prompt",
        "task_direction.code_prompt",
        "completion_review.prompt",
        "implementation_checkpoint.prompt",
        "context_compaction.gate_prompt",
        "context_compaction.retry_prompt",
    }


def test_catalog_exposes_quality_fast_and_diagnostic_presets():
    catalog = RuntimePolicyCatalog.load()

    assert {
        "coding-default",
        "coding-fast",
        "coding-diagnostic",
    }.issubset(catalog.policies)
    assert catalog.get("coding-fast").policy.completion_review.enabled is False
    assert catalog.get("coding-diagnostic").policy.implementation_checkpoint.enabled is False


def test_profile_overrides_are_typed_and_do_not_mutate_catalog_policy():
    catalog = RuntimePolicyCatalog.load()
    baseline = copy.deepcopy(catalog.get().policy.to_payload())
    resolved = resolve_runtime_policy(
        {
            "policy_id": "coding-default",
            "overrides": {
                "completion_review": {
                    "passes": 2,
                    "prompt": "Review this implementation once more.",
                },
                "implementation_checkpoint": {
                    "evidence_operation_limit": 7,
                },
                "context_compaction": {
                    "every_tool_calls": 40,
                    "gate_prompt": "Compact only decision-relevant tool evidence.",
                },
            },
        },
        catalog=catalog,
    )

    assert resolved.policy.completion_review.passes == 2
    assert resolved.policy.completion_review.prompt == "Review this implementation once more."
    assert resolved.policy.implementation_checkpoint.evidence_operation_limit == 7
    assert resolved.policy.context_compaction.every_tool_calls == 40
    assert (
        resolved.policy.context_compaction.gate_prompt
        == "Compact only decision-relevant tool evidence."
    )
    assert catalog.get().policy.to_payload() == baseline
    prompt = next(
        item
        for item in resolved.manifest["prompts"]
        if item["layer"] == "completion_review.prompt"
    )
    assert prompt["source"] == "agent_profile.runtime_policy"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "agent_profile.runtime_policy must be an object"),
        ({"unknown": True}, "unknown fields"),
        ({"policy_id": "missing"}, "unknown runtime policy"),
        (
            {"overrides": {"completion_review": {"passes": 0}}},
            "completion_review.passes must be between 1 and 5",
        ),
        (
            {"overrides": {"implementation_checkpoint": {"enabled": "yes"}}},
            "implementation_checkpoint.enabled must be a boolean",
        ),
        (
            {"overrides": {"task_direction": {"extra": True}}},
            "task_direction has unknown fields",
        ),
    ],
)
def test_invalid_profile_runtime_policy_is_rejected(payload, message):
    with pytest.raises(RuntimePolicyValidationError, match=message):
        resolve_runtime_policy(payload)


def test_catalog_rejects_prompt_path_escape(tmp_path):
    config_dir = tmp_path / "config"
    policy_dir = config_dir / "runtime_policies"
    policy_dir.mkdir(parents=True)
    (config_dir / "runtimePolicies.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_policy_id": "bad",
                "policies": {"bad": "runtime_policies/bad.json"},
            }
        ),
        encoding="utf-8",
    )
    (policy_dir / "bad.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy_id": "bad",
                "version": "1",
                "description": "",
                "task_direction": {
                    "enabled": True,
                    "required_tools": [],
                    "analysis_tools": [],
                    "core_prompt_file": "../../outside.txt",
                    "code_prompt_file": "../../outside.txt",
                },
                "completion_review": {
                    "enabled": False,
                    "passes": 1,
                    "require_tool_executions": True,
                    "require_done_criteria": False,
                    "require_resolved_risks": False,
                    "prompt_file": "../../outside.txt",
                },
                "implementation_checkpoint": {
                    "enabled": False,
                    "evidence_operation_limit": 1,
                    "workspace_tool": "workspace_exec",
                    "direct_evidence_tools": [],
                    "workspace_evidence_kinds": [],
                    "patch_tools": [],
                    "workspace_patch_kinds": [],
                    "prompt_file": "../../outside.txt",
                },
                "context_compaction": {
                    "enabled": True,
                    "every_tool_calls": 30,
                    "input_tokens": 0,
                    "current_input_tokens": 0,
                    "output_tokens": 0,
                    "context_percent": 35,
                    "max_candidate_chars": 50000,
                    "gate_prompt_file": "../../outside.txt",
                    "retry_prompt_file": "../../outside.txt",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimePolicyValidationError, match="escapes the config directory"):
        RuntimePolicyCatalog.load(str(tmp_path))
