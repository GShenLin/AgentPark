from __future__ import annotations

from src import workspace_settings


def memory_local_config_from_defaults(payload: dict) -> dict:
    storage = payload.get("storage")
    if storage is None:
        return {}
    if not isinstance(storage, dict):
        raise ValueError("config.json field 'storage' must be an object")
    local_config = {}
    if "memoriesPath" in storage:
        local_config["memoriesPath"] = storage["memoriesPath"]
    return workspace_settings.validate_memory_local_config(local_config)


def defaults_without_memory_local_config(payload: dict) -> dict:
    defaults = dict(payload)
    storage = defaults.get("storage")
    if not isinstance(storage, dict):
        return defaults
    persisted_storage = dict(storage)
    persisted_storage.pop("memoriesPath", None)
    if persisted_storage:
        defaults["storage"] = persisted_storage
    else:
        defaults.pop("storage", None)
    return defaults


def defaults_with_memory_local_config(payload: dict, local_config: dict) -> dict:
    defaults = defaults_without_memory_local_config(payload)
    memories_path = local_config.get("memoriesPath")
    if memories_path is None:
        return defaults
    storage = defaults.get("storage")
    merged_storage = dict(storage) if isinstance(storage, dict) else {}
    merged_storage["memoriesPath"] = memories_path
    defaults["storage"] = merged_storage
    return defaults
