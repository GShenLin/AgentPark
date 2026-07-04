from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any


CODEX_MODELS_RELATIVE_PATH = os.path.join(
    "codex",
    "codex-rs",
    "models-manager",
    "models.json",
)
DEFAULT_CODEX_MODEL_SLUG = "gpt-5.5"


def resolve_agent_codex_base_instructions(
    agent: object,
    *,
    explicit_system_prompt: object = None,
) -> str:
    explicit = str(explicit_system_prompt or "").strip()
    if explicit:
        return explicit
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        return ""
    if not _codex_base_instructions_enabled(config):
        return ""
    inline = str(config.get("codexBaseInstructionsText") or config.get("codex_base_instructions_text") or "").strip()
    if inline:
        return inline
    return load_codex_base_instructions(
        model=str(config.get("model") or "").strip(),
        models_path=str(config.get("codexModelsPath") or config.get("codex_models_path") or "").strip(),
    )


def load_codex_base_instructions(*, model: str = "", models_path: str = "") -> str:
    path = _resolve_models_path(models_path)
    models = _load_codex_models(path)
    if not models:
        return ""
    selected = _select_model(models, model)
    return str(selected.get("base_instructions") or "").strip() if isinstance(selected, dict) else ""


def _codex_base_instructions_enabled(config: dict[str, Any]) -> bool:
    for key in ("codexBaseInstructions", "codex_base_instructions"):
        if key in config:
            return config.get(key) is not False
    return True


def _resolve_models_path(models_path: str = "") -> str:
    if models_path:
        return os.path.normpath(os.path.abspath(os.path.expanduser(models_path)))
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, CODEX_MODELS_RELATIVE_PATH)


@lru_cache(maxsize=8)
def _load_codex_models(path: str) -> tuple[dict[str, Any], ...]:
    if not path or not os.path.isfile(path):
        return tuple()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return tuple()
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
        if str(item.get("slug") or "").strip().lower() == DEFAULT_CODEX_MODEL_SLUG:
            return item
    return models[0] if models else {}
