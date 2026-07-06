from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any


INSTRUCTIONS_MODEL_CATALOG_RELATIVE_PATH = os.path.join(
    "instruction",
    "models.json",
)
DEFAULT_INSTRUCTIONS_MODEL_SLUG = "gpt-5.5"


def resolve_agent_default_instructions(agent: object) -> str:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        return ""
    if not _default_instructions_enabled(config):
        return ""
    inline = str(config.get("defaultInstructionsText") or config.get("default_instructions_text") or "").strip()
    if inline:
        return inline
    return load_default_instructions(
        model=str(config.get("model") or "").strip(),
    )


def load_default_instructions(*, model: str = "") -> str:
    path = _models_catalog_path()
    if not os.path.isfile(path):
        return ""
    models = _load_instruction_models(path)
    if not models:
        return ""
    selected = _select_model(models, model)
    return _model_instructions(selected)


def _default_instructions_enabled(config: dict[str, Any]) -> bool:
    for key in ("defaultInstructions", "default_instructions"):
        if key in config:
            return config.get(key) is not False
    return True


def _models_catalog_path() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, INSTRUCTIONS_MODEL_CATALOG_RELATIVE_PATH)


@lru_cache(maxsize=8)
def _load_instruction_models(path: str) -> tuple[dict[str, Any], ...]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return tuple()
    return tuple(model for model in models if isinstance(model, dict))


def _select_model(models: tuple[dict[str, Any], ...], model: str) -> dict[str, Any]:
    wanted = model.strip().lower()
    if wanted:
        for item in models:
            if str(item.get("slug") or "").strip().lower() == wanted:
                return item
    for item in models:
        if str(item.get("slug") or "").strip().lower() == DEFAULT_INSTRUCTIONS_MODEL_SLUG:
            return item
    return models[0] if models else {}


def _model_instructions(model: dict[str, Any]) -> str:
    if not isinstance(model, dict):
        return ""
    return str(model.get("instructions") or "").strip()
