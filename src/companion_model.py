"""The explicit Provider ID / Model ID binding used by Companion settings and recovery."""
from __future__ import annotations

from src.provider_models import resolve_provider_model


def validate_companion_model(config: dict, providers: dict, *, required: bool = False) -> None:
    for field in ("provider_id", "model"):
        if field in config and not isinstance(config[field], str):
            raise ValueError(f"Companion {field} must be a string.")
    provider_id = config.get("provider_id", "").strip()
    model_id = config.get("model", "").strip()
    if not required and not provider_id and not model_id:
        return
    if not provider_id or not model_id:
        raise ValueError("Select both Provider ID and Model ID in Settings > Companion.")
    provider = providers.get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"Companion provider is not configured: {provider_id}")
    resolve_provider_model({**provider, "id": provider_id}, model_id)
