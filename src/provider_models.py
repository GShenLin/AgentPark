"""Provider model allow-list normalization and selection."""

from __future__ import annotations

from typing import Any


def provider_model_ids(provider: dict[str, Any]) -> list[str]:
    """Return configured model IDs in their declared order."""
    raw_models = provider.get("models")
    if isinstance(raw_models, list):
        return _normalize_model_ids(raw_models)
    raw_model = provider.get("model")
    if isinstance(raw_model, list):
        return _normalize_model_ids(raw_model)
    model_id = str(raw_model or "").strip()
    return [model_id] if model_id else []


def resolve_provider_model(provider: dict[str, Any], requested_model: object = None) -> str:
    """Resolve a node model against the provider allow-list."""
    model_ids = provider_model_ids(provider)
    requested = str(requested_model or "").strip()
    if requested:
        if requested not in model_ids:
            provider_id = str(provider.get("id") or "").strip()
            scope = f" for provider '{provider_id}'" if provider_id else ""
            raise ValueError(f"Model '{requested}' is not allowed{scope}.")
        return requested
    return model_ids[0] if model_ids else ""


def _normalize_model_ids(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        model_id = str(value or "").strip()
        if model_id and model_id not in result:
            result.append(model_id)
    return result
