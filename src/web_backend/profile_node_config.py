from __future__ import annotations

import copy
from typing import Any

from .node_config_service import RESERVED_NODE_CONFIG_FIELDS, RUNTIME_STATE_FIELDS
from .profile_storage import ProfileValidationError


PROFILE_EXCLUDED_NODE_FIELDS = {
    *RESERVED_NODE_CONFIG_FIELDS,
    *RUNTIME_STATE_FIELDS,
    "schema",
    "_config_version",
    "pending_count",
}


def node_fields_from_config(config: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in config.items():
        if not isinstance(key, str) or not key.strip() or key in PROFILE_EXCLUDED_NODE_FIELDS:
            continue
        fields[key] = copy.deepcopy(value)
    return fields


def node_profile_config(config: dict[str, Any]) -> dict[str, Any]:
    node_id = str(config.get("node_id") or "").strip()
    type_id = str(config.get("type_id") or "").strip()
    if not node_id:
        raise ProfileValidationError("node config is missing node_id")
    if not type_id:
        raise ProfileValidationError("node config is missing type_id")
    payload: dict[str, Any] = {
        "node_id": node_id,
        "graph_id": str(config.get("graph_id") or "").strip(),
        "type_id": type_id,
        "name": str(config.get("name") or node_id).strip() or node_id,
        "fields": node_fields_from_config(config),
    }
    ui = config.get("ui")
    if isinstance(ui, dict):
        payload["ui"] = copy.deepcopy(ui)
    for key in ("input_num", "output_num"):
        if config.get(key) is not None:
            payload[key] = config[key]
    return payload


def node_config_from_profile(profile_node: dict[str, Any], *, target_graph_id: str) -> dict[str, Any]:
    if not isinstance(profile_node, dict):
        raise ProfileValidationError("profile node config must be an object")
    node_id = str(profile_node.get("node_id") or "").strip()
    type_id = str(profile_node.get("type_id") or "").strip()
    if not node_id:
        raise ProfileValidationError("profile node config is missing node_id")
    if not type_id:
        raise ProfileValidationError(f"profile node {node_id} is missing type_id")
    fields = profile_node.get("fields", {})
    if not isinstance(fields, dict):
        raise ProfileValidationError(f"profile node {node_id} fields must be an object")

    payload: dict[str, Any] = {
        "node_id": node_id,
        "type_id": type_id,
        "name": str(profile_node.get("name") or node_id).strip() or node_id,
        "graph_id": target_graph_id,
    }
    ui = profile_node.get("ui")
    if isinstance(ui, dict):
        payload["ui"] = copy.deepcopy(ui)
    for key in ("input_num", "output_num"):
        if profile_node.get(key) is not None:
            payload[key] = profile_node[key]
    for key, value in fields.items():
        if isinstance(key, str) and key.strip() and key not in PROFILE_EXCLUDED_NODE_FIELDS:
            payload[key] = copy.deepcopy(value)
    return payload


__all__ = [
    "PROFILE_EXCLUDED_NODE_FIELDS",
    "node_config_from_profile",
    "node_fields_from_config",
    "node_profile_config",
]
