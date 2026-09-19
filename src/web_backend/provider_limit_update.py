from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from src.provider_limit_schema import provider_limit_path, read_provider_limit_file
from src.provider_models import provider_model_ids


@dataclass(frozen=True)
class ProviderLimitUpdatePlan:
    path: str
    content: str
    copied_targets: tuple[str, ...]
    added_models: tuple[tuple[str, str], ...]
    missing_sources: tuple[str, ...]


def prepare_provider_limit_update_plan(
    raw_copies: object,
    raw_model_additions: object,
    providers: dict[str, Any],
) -> ProviderLimitUpdatePlan | None:
    copies = _parse_copy_requests(raw_copies, providers)
    additions = _parse_model_additions(raw_model_additions, providers)
    if not copies and not additions:
        return None

    document = read_provider_limit_file()
    document.pop("path", None)
    entries = document.get("providers")
    if not isinstance(entries, dict):
        raise ValueError("ProviderLimit.json field 'providers' must be an object")

    copied_targets: list[str] = []
    missing_sources: list[str] = []
    for source_id, target_id in copies:
        source_entry = entries.get(source_id)
        if not isinstance(source_entry, dict):
            missing_sources.append(source_id)
            continue

        target_entry = copy.deepcopy(source_entry)
        _retarget_entry(target_entry, target_id, providers[target_id])
        entries[target_id] = target_entry
        copied_targets.append(target_id)

    added_models: list[tuple[str, str]] = []
    for provider_id, model_id in additions:
        provider = providers[provider_id]
        entry = entries.get(provider_id)
        if not isinstance(entry, dict):
            entry = {
                "provider_id": provider_id,
                "type": str(provider.get("type") or "").strip(),
                "model": provider_model_ids(provider)[0] if provider_model_ids(provider) else "",
                "tested_at": "",
                "available_model_ids": [],
                "manual_model_ids": [],
                "features": {},
                "unsupported": {},
            }
            entries[provider_id] = entry
        _append_unique_model_id(entry, "manual_model_ids", model_id)
        _append_unique_model_id(entry, "available_model_ids", model_id)
        added_models.append((provider_id, model_id))

    changed = bool(copied_targets or added_models)
    return ProviderLimitUpdatePlan(
        path=provider_limit_path(),
        content=json.dumps(document, ensure_ascii=False, indent=2) + "\n" if changed else "",
        copied_targets=tuple(copied_targets),
        added_models=tuple(added_models),
        missing_sources=tuple(missing_sources),
    )


def _retarget_entry(entry: dict[str, Any], provider_id: str, provider: dict[str, Any]) -> None:
    entry["provider_id"] = provider_id
    entry["type"] = str(provider.get("type") or entry.get("type") or "").strip()
    provider_models = provider_model_ids(provider)
    entry["model"] = (provider_models[0] if provider_models else str(entry.get("model") or "").strip())
    channels = entry.get("channels")
    if not isinstance(channels, dict):
        return
    for channel_entry in channels.values():
        if not isinstance(channel_entry, dict):
            continue
        channel_entry["provider_id"] = provider_id
        channel_entry["type"] = entry["type"]
        channel_entry["model"] = entry["model"]


def _append_unique_model_id(entry: dict[str, Any], key: str, model_id: str) -> None:
    current = entry.get(key)
    model_ids = [
        str(value).strip()
        for value in current
        if str(value).strip()
    ] if isinstance(current, list) else []
    if model_id not in model_ids:
        model_ids.append(model_id)
    entry[key] = model_ids


def _parse_copy_requests(raw_copies: object, providers: dict[str, Any]) -> list[tuple[str, str]]:
    if raw_copies is None:
        return []
    if not isinstance(raw_copies, list):
        raise ValueError("provider_limit_copies must be a list")

    copies: list[tuple[str, str]] = []
    target_ids: set[str] = set()
    for index, item in enumerate(raw_copies):
        if not isinstance(item, dict):
            raise ValueError(f"provider_limit_copies[{index}] must be an object")
        source_id = str(item.get("source_provider_id") or "").strip()
        target_id = str(item.get("target_provider_id") or "").strip()
        if not source_id or not target_id:
            raise ValueError(
                f"provider_limit_copies[{index}] requires source_provider_id and target_provider_id"
            )
        if source_id == target_id:
            raise ValueError(f"provider_limit_copies[{index}] source and target must differ")
        if target_id not in providers:
            raise ValueError(f"provider limit copy target '{target_id}' is not in modelProvider.json")
        if target_id in target_ids:
            raise ValueError(f"provider limit copy target '{target_id}' is duplicated")
        target_ids.add(target_id)
        copies.append((source_id, target_id))
    return copies


def _parse_model_additions(raw_additions: object, providers: dict[str, Any]) -> list[tuple[str, str]]:
    if raw_additions is None:
        return []
    if not isinstance(raw_additions, list):
        raise ValueError("provider_model_additions must be a list")

    additions: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_additions):
        if not isinstance(item, dict):
            raise ValueError(f"provider_model_additions[{index}] must be an object")
        provider_id = str(item.get("provider_id") or "").strip()
        model_id = str(item.get("model_id") or "").strip()
        if not provider_id or not model_id:
            raise ValueError(f"provider_model_additions[{index}] requires provider_id and model_id")
        if provider_id not in providers:
            raise ValueError(f"provider model addition target '{provider_id}' is not in modelProvider.json")
        addition = (provider_id, model_id)
        if addition in seen:
            raise ValueError(f"provider model addition '{provider_id}/{model_id}' is duplicated")
        seen.add(addition)
        additions.append(addition)
    return additions
