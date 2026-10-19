"""Companion's persisted Preset reference and effective runtime configuration.

Agent Presets own model, instructions and capabilities. The Companion node owns
identity, working directory and state. Standalone --config documents (including
startup repair snapshots) remain ordinary, explicitly supplied node configs.
"""
from __future__ import annotations

from copy import deepcopy
import os
from typing import Any, Callable

from src.companion_model import validate_companion_model
from src.companion_paths import companion_node_config_path
from src.config_loader import ConfigLoader
from src.web_backend import runtime_paths
from src.web_backend.node_config_service import (
    RESERVED_NODE_CONFIG_FIELDS, RUNTIME_STATE_FIELDS, node_config_service,
)
from src.web_backend.profile_storage import (
    AGENT_PROFILE_DIR, get_profile, profile_category_dir, profile_file_path,
    upsert_profile, validate_profile_id,
)


COMPANION_LOCAL_FIELDS = RESERVED_NODE_CONFIG_FIELDS | RUNTIME_STATE_FIELDS | {
    "profile_id", "working_path",
}


def companion_profile(config: dict[str, Any]) -> dict[str, Any]:
    profile_id = config.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("Select a Preset in Settings > Companion (profile_id is required).")
    profile = get_profile(profile_category_dir(AGENT_PROFILE_DIR), validate_profile_id(profile_id))
    if profile is None:
        raise ValueError(f"Companion Preset not found: {profile_id}")
    if profile.get("node_type_id") != "agent_node":
        raise ValueError(f"Companion Preset {profile_id} must use node_type_id agent_node")
    fields = profile.get("fields")
    if not isinstance(fields, dict):
        raise ValueError(f"Companion Preset {profile_id} fields must be an object")
    forbidden = set(fields) & (COMPANION_LOCAL_FIELDS - {"working_path"})
    if forbidden:
        raise ValueError(f"Companion Preset contains node identity/state fields: {', '.join(sorted(forbidden))}")
    return profile


def resolve_companion_config(config: dict[str, Any]) -> dict[str, Any]:
    unknown = set(config) - COMPANION_LOCAL_FIELDS
    if unknown:
        raise ValueError("Configure Companion fields in its Preset instead: " + ", ".join(sorted(unknown)))
    if config.get("type_id", "agent_node") != "agent_node":
        raise ValueError("Companion type_id must be agent_node")
    if "working_path" in config and not isinstance(config["working_path"], str):
        raise ValueError("Companion working_path must be a string")
    profile = companion_profile(config)
    fields = deepcopy(profile["fields"])
    providers = ConfigLoader().get_all_providers()
    validate_companion_model(fields, providers, required=True)
    provider = providers[fields["provider_id"].strip()]
    if "chat" not in provider.get("supportmode", []):
        raise ValueError(f"Companion Preset {profile['id']} provider must support chat")
    return {**fields, **deepcopy(config)}


def _uses_preset(path: str, config: dict[str, Any]) -> bool:
    canonical = companion_node_config_path(runtime_paths._get_graphs_dir())
    return "profile_id" in config or os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(canonical))


def read_companion_config(path: str) -> dict[str, Any]:
    config = node_config_service.read_strict(path)
    return resolve_companion_config(config) if _uses_preset(path, config) else config


def companion_config_signature(path: str) -> tuple[tuple[int, int, int], ...]:
    paths = [path]
    config = node_config_service.read_persistent_strict(path)
    if _uses_preset(path, config):
        profile = companion_profile(config)
        paths.append(profile_file_path(profile_category_dir(AGENT_PROFILE_DIR), profile["id"]))
    return tuple((stat.st_mtime_ns, stat.st_size, stat.st_ino) for stat in map(os.stat, paths))


def update_companion_fields(path: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    config = node_config_service.read_persistent_strict(path)
    if _uses_preset(path, config):
        profile = companion_profile(config)
        mutate(profile["fields"])
        validate_companion_model(profile["fields"], ConfigLoader().get_all_providers(), required=True)
        upsert_profile(profile_category_dir(AGENT_PROFILE_DIR), profile)
    else:
        node_config_service.update(path, mutate)
    return read_companion_config(path)
