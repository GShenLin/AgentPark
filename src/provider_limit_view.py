"""Join persisted probe results onto the current provider catalog for settings."""

from __future__ import annotations

from typing import Any

from src.config_loader import ConfigLoader
from src.provider_limit_schema import read_provider_limit_file
from src.provider_models import provider_model_ids


def read_current_provider_limits() -> dict[str, Any]:
    """Use configured providers as membership; snapshots supply test evidence only.

    Read the catalog on every request, including job polls, so file edits and
    settings saves take effect without another probe. Historical snapshots stay
    on disk, and loading settings never resolves credentials or makes requests.
    Snapshot progress fields continue to describe the original probe run.
    """
    catalog = ConfigLoader().get_provider_catalog()
    document = read_provider_limit_file()
    snapshots = document.get("providers")
    if not isinstance(snapshots, dict):
        raise ValueError("ProviderLimit.json field 'providers' must be an object")

    providers: dict[str, Any] = {}
    for provider_id, provider in catalog.items():
        model_ids = provider_model_ids(provider)
        entry = {
            "provider_id": provider_id,
            "type": provider["type"],
            "model": provider["model"],
            "tested_at": "",
            "available_model_ids": model_ids,
            "features": {},
            "unsupported": {},
        }
        if provider_id in snapshots:
            snapshot = snapshots[provider_id]
            if not isinstance(snapshot, dict):
                raise ValueError(f"ProviderLimit.json provider '{provider_id}' must be an object")
            entry.update(snapshot)
        providers[provider_id] = entry
    return {**document, "providers": providers}
