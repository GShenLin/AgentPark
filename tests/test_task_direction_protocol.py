from pathlib import Path

from src.runtime_policy import resolve_runtime_policy


ROOT = Path(__file__).parents[1]


def test_default_code_task_protocol_is_catalog_owned_and_bounded():
    resolved = resolve_runtime_policy(None)
    prompt = resolved.policy.task_direction.code_prompt
    source = (
        ROOT
        / "config"
        / "runtime_policies"
        / "prompts"
        / "coding-task-direction.txt"
    ).read_text(encoding="utf-8").strip()

    assert prompt == source
    assert "task-direction ledger" in prompt
    assert "production entry paths" in prompt
    assert "Do not hide errors" in prompt
    assert "three or more" in prompt
    assert "run the focused checks" in prompt
    assert "Report failing gates as evidence" in prompt
    assert "context_checkpoint" not in prompt


def test_profile_code_prompt_override_is_effective_and_auditable():
    resolved = resolve_runtime_policy(
        {
            "overrides": {
                "task_direction": {
                    "code_prompt": "Use the supplied task contract exactly.",
                }
            }
        }
    )

    assert (
        resolved.policy.task_direction.code_prompt
        == "Use the supplied task contract exactly."
    )
    prompt_manifest = next(
        item
        for item in resolved.manifest["prompts"]
        if item["layer"] == "task_direction.code_prompt"
    )
    assert prompt_manifest["source"] == "agent_profile.runtime_policy"
