import json
import os

from src.web_backend.node_config_service import read_node_config_optional
from src.web_backend.node_config_service import RUNTIME_STATE_FIELDS


def load_node_config_file(node_dir: str, *, filename: str = "config.json") -> dict:
    config_path = os.path.join(node_dir, filename)
    if not os.path.exists(config_path):
        return {}
    if filename == "config.json":
        try:
            payload = read_node_config_optional(config_path)
        except Exception as exc:
            if "must be a JSON object" in str(exc):
                raise ValueError(f"Node config '{config_path}' must contain a JSON object.") from exc
            raise ValueError(f"Failed to read node config '{config_path}': {exc}") from exc
        payload.pop("schemaVersion", None)
        for key in RUNTIME_STATE_FIELDS:
            payload.pop(key, None)
        return payload
    try:
        with open(config_path, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except Exception as exc:
        raise ValueError(f"Failed to read node config '{config_path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Node config '{config_path}' must contain a JSON object.")
    return payload


def merge_node_config_overlay(ctx: dict, node_dir: str) -> dict:
    merged = dict(ctx)
    merged.update(load_node_config_file(node_dir))
    return merged
