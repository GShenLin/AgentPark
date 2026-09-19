"""Persist discovered model IDs into the provider configuration."""

from __future__ import annotations

import json

from src.file_transaction import atomic_write_text
from src.provider_models import provider_model_ids


def append_discovered_model_ids(path: str, provider_id: str, model_ids: list[str]) -> None:
    """Append missing IDs while preserving raw credentials and unrelated settings."""
    if not model_ids:
        return
    if any(not isinstance(value, str) or not value.strip() for value in model_ids):
        raise ValueError("Discovered model IDs must be non-empty strings.")

    # Reload after the network request so edits made during discovery are retained.
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), dict):
        raise ValueError("modelProvider.json must contain a providers object.")
    provider = payload["providers"].get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"Provider '{provider_id}' no longer has a valid configuration.")
    if "models" in provider and not isinstance(provider["models"], list):
        raise ValueError(f"Provider '{provider_id}' models must be an array.")
    raw_models = provider.get("models", provider.get("model", ""))
    if not isinstance(raw_models, (str, list)):
        raise ValueError(f"Provider '{provider_id}' must declare model IDs.")
    if isinstance(raw_models, list) and any(
        not isinstance(value, str) or not value.strip() for value in raw_models
    ):
        raise ValueError(f"Provider '{provider_id}' model IDs must be non-empty strings.")

    existing = provider_model_ids(provider)
    merged = list(dict.fromkeys([*existing, *(value.strip() for value in model_ids)]))
    if merged == existing:
        return
    model_field = "models" if "models" in provider else "model"
    provider[model_field] = merged
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
