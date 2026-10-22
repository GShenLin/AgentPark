"""Own the DSH launch overlay independently of its one-time settings importer."""
from __future__ import annotations

import json
from pathlib import Path

from src.file_transaction import atomic_write_text


def configure_runtime(home: Path, model: str, base_url: str) -> Path:
    path = home / "agentpark.patch.json"
    if path.exists():
        patches = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(patches, list):
            raise ValueError("Invalid DeepSeek Harness runtime overlay.")
        entries = [p for p in patches if isinstance(p, dict) and p.get("id") == "llm-pi-ai"]
        if len(entries) != 1:
            raise ValueError("DeepSeek Harness overlay requires one llm-pi-ai entry.")
        config = {"llm-pi-ai": entries[0].get("config")}
    else:
        # One-time adoption of configurations written by AgentPark before DSH
        # replaced settings.yaml with profile overlays. DSH renames consumed
        # settings to .imported; neither file is our durable model registry.
        pending = home / "settings.yaml"
        imported = home / "settings.yaml.imported"
        source = pending if pending.exists() else imported
        config = json.loads(source.read_text(encoding="utf-8")) if source.exists() else None
    models = _models(config, model)
    patches = [
        {"id": "llm-pi-ai", "config": {"providers": {"agentpark": {
            "apiKeyEnv": "AGENTPARK_HARNESS_TOKEN", "api": "openai-responses",
            "baseURL": base_url, "models": models}}}},
        {"id": "agent-default-model", "config": {"provider": "agentpark", "model": model}},
    ]
    atomic_write_text(str(path), json.dumps(patches, ensure_ascii=False, indent=2), encoding="utf-8")
    pending = home / "settings.yaml"
    if pending.exists():
        # Preserve the obsolete document, but do not let the native asynchronous
        # importer overwrite this turn's explicit launch overlay.
        archived = home / "settings.yaml.agentpark-migrated"
        if archived.exists():
            raise ValueError(f"DeepSeek settings migration archive already exists: {archived}")
        pending.rename(archived)
    return path


def _models(config: object, model: str) -> list[dict[str, str]]:
    ids: list[str] = []
    if config is not None:
        value = config
        for key in ("llm-pi-ai", "providers", "agentpark", "models"):
            if not isinstance(value, dict) or key not in value:
                raise ValueError("Invalid DeepSeek Harness model configuration for session resume.")
            value = value[key]
        if not isinstance(value, list) or not value:
            raise ValueError("DeepSeek Harness models must be a nonempty array.")
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("DeepSeek Harness model requires a nonempty id.")
            if item["id"] not in ids:
                ids.append(item["id"])
    if model not in ids:
        ids.append(model)
    return [{"id": item} for item in ids]
