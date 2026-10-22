"""OpenCode ACP selection and AgentPark-owned provider configuration."""
from __future__ import annotations

import os
from src.web_backend.node_config_service import read_node_config_optional

RUNTIME_MODEL = "agentpark/selected"


def runtime_config(base_url: str) -> dict:
    return {
        "model": RUNTIME_MODEL,
        "providers": {"agentpark": {
            "name": "AgentPark", "env": ["AGENTPARK_HARNESS_TOKEN"],
            "package": "@opencode/ai/providers/openai-compatible/responses",
            "settings": {"baseURL": base_url, "apiKey": "{env:AGENTPARK_HARNESS_TOKEN}", "transport": "http"},
            "models": {"selected": {"name": "AgentPark selected model"}},
        }},
    }


def agent_mode(context) -> str:
    config = read_node_config_optional(context.config_path) if os.path.isfile(context.config_path) else {}
    value = {**context.values, **config}.get("agent_mode", "build")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("OpenCode agent_mode must be a non-empty string.")
    return value.strip()


def select_option(control: dict, config_id: str, value: str) -> str:
    configs = control.get("configOptions")
    if not isinstance(configs, list):
        raise ValueError("OpenCode did not advertise ACP configOptions.")
    matches = [item for item in configs if isinstance(item, dict) and item.get("id") == config_id]
    if len(matches) != 1 or matches[0].get("type") != "select":
        raise ValueError(f"OpenCode did not advertise one selectable {config_id} option.")
    options = matches[0].get("options")
    if not isinstance(options, list):
        raise ValueError(f"OpenCode {config_id} options must be an array.")
    values = []
    for item in options:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid OpenCode {config_id} option.")
        if "group" in item:
            group = item.get("options")
            if not isinstance(group, list) or any(not isinstance(child, dict) for child in group):
                raise ValueError(f"Invalid OpenCode {config_id} option group.")
            values.extend(child.get("value") for child in group)
        else:
            values.append(item.get("value"))
    if values.count(value) != 1:
        raise ValueError(f"OpenCode {config_id} is unavailable: {value}. Check the selected agent and AgentPark Provider configuration.")
    return value
