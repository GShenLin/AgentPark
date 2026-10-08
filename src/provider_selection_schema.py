"""Shared Provider/Model fields for node configuration forms."""

from typing import Any

from src.provider_models import provider_model_ids


def provider_selection_schema(
    provider: dict[str, Any] | None = None,
    *,
    provider_options: list[dict[str, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "provider_id": {
            "type": "select",
            "label": "provider_id",
            "options": [] if provider_options is None else list(provider_options),
            "description": "Select a configured Provider supported by this node.",
        },
        "model": {
            "type": "select",
            "label": "model",
            "options": [
                {"value": model, "label": model}
                for model in provider_model_ids({} if provider is None else provider)
            ],
            "description": "Select a model ID allowed by the selected Provider.",
        },
    }
