from __future__ import annotations

import json
from typing import Any

from src.web_backend.node_config_service import node_config_service

from .common import node_config_path


def validate_config(args) -> dict[str, Any]:
    path = node_config_path(args.graph, args.node)
    config = node_config_service.read_strict(path)
    return {"status": "success", "config_path": path, "keys": sorted(config.keys())}


def diff_config(args) -> dict[str, Any]:
    path = node_config_path(args.graph, args.node)
    config = node_config_service.read_strict(path)
    with open(args.fields, "r", encoding="utf-8") as handle:
        fields = json.load(handle)
    if not isinstance(fields, dict):
        raise ValueError("--fields file must contain a JSON object")
    changed_fields = sorted(key for key, value in fields.items() if config.get(key) != value)
    return {
        "status": "success",
        "config_path": path,
        "changed_fields": changed_fields,
        "before": {key: config.get(key) for key in changed_fields},
        "after": {key: fields.get(key) for key in changed_fields},
    }
