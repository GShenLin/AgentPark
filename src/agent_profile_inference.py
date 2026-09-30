"""Resolve AgentProfile inference settings for internal, tool-free model tasks."""
from __future__ import annotations

from dataclasses import dataclass

from src.config_loader import ConfigLoader
from src.provider_models import resolve_provider_model
from src.providers import create_agent
from src.providers.agent_config import AgentConfig
from src.web_backend.profile_storage import (
    AGENT_PROFILE_DIR, get_profile, profile_category_dir, validate_profile_id,
)


@dataclass(frozen=True)
class AgentProfileInference:
    profile_id: str
    provider_id: str
    model_id: str
    system_prompt: str
    instruction: str
    thinking: str
    reasoning_effort: str
    reasoning_summary: str

    def instructions(self, task_instructions: str) -> str:
        # The internal task owns its output contract; profile guidance precedes it.
        return "\n\n".join(text for text in (self.system_prompt, self.instruction, task_instructions) if text)

    def create_agent(self, memory_path: str, task_instructions: str):
        return create_agent(
            self.provider_id, memory_file_path=memory_path,
            system_prompt=self.instructions(task_instructions), internal_memory_enabled=False,
            model_id=self.model_id,
            agent_config=AgentConfig(
                run_tools=False, web_search="disabled", stream=False,
                thinking=self.thinking, reasoning_effort=self.reasoning_effort,
                reasoning_summary=self.reasoning_summary,
            ),
        )


def resolve_agent_profile_inference(profile_id: str) -> AgentProfileInference:
    if not isinstance(profile_id, str):
        raise ValueError("AgentProfile profile_id must be a string")
    safe_id = validate_profile_id(profile_id)
    profile = get_profile(profile_category_dir(AGENT_PROFILE_DIR), safe_id)
    if profile is None:
        raise ValueError(f"AgentProfile not found: {safe_id}")
    if profile.get("node_type_id") != "agent_node":
        raise ValueError(f"AgentProfile {safe_id} must use node_type_id agent_node")
    fields = profile.get("fields")
    if not isinstance(fields, dict):
        raise ValueError(f"AgentProfile {safe_id} fields must be an object")

    def text(key: str, default: str = "") -> str:
        value = fields.get(key, default)
        if not isinstance(value, str):
            raise ValueError(f"AgentProfile {safe_id} field {key} must be a string")
        return value.strip()

    provider_id = text("provider_id")
    if not provider_id:
        raise ValueError(f"AgentProfile {safe_id} provider_id is required")
    config = ConfigLoader().get_provider_config(provider_id)
    model_id = resolve_provider_model({**config, "id": provider_id}, text("model"))
    if not model_id:
        raise ValueError(f"AgentProfile {safe_id} requires a configured model")
    if "chat" not in config.get("supportmode", []):
        raise ValueError(f"AgentProfile {safe_id} must support chat")
    thinking = text("thinking", "disabled")
    if thinking not in {"enabled", "disabled"}:
        raise ValueError(f"AgentProfile {safe_id} thinking must be enabled or disabled")
    effort = text("reasoning_effort", "high")
    if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "auto"}:
        raise ValueError(f"AgentProfile {safe_id} has invalid reasoning_effort: {effort}")
    summary = text("reasoning_summary")
    if summary not in {"", "auto", "concise", "detailed", "disabled"}:
        raise ValueError(f"AgentProfile {safe_id} has invalid reasoning_summary: {summary}")
    return AgentProfileInference(safe_id, provider_id, model_id, text("system_prompt"),
                                 text("instruction"), thinking, effort, summary)


def validate_default_agent_profiles(payload: dict) -> None:
    for section, keys in (
        ("conversationContext", ("profile_id",)),
        ("longTermMemory", ("extract_profile_id", "consolidation_profile_id")),
    ):
        for key in keys:
            if key in payload.get(section, {}):
                resolve_agent_profile_inference(payload[section][key])
