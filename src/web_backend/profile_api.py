from __future__ import annotations

import copy
import json
import os
import shutil
from typing import Any

from . import runtime_paths
from .graph_api_storage import _write_graph_config
from .graph_runtime_registry import GraphConfigReadError
from .node_config_errors import NodeConfigReadError, NodeConfigWriteError
from .node_config_service import RESERVED_NODE_CONFIG_FIELDS, RUNTIME_STATE_FIELDS, node_config_service
from .profile_storage import (
    AGENT_PROFILE_DIR,
    GRAPH_PROFILE_DIR,
    ProfileStorageError,
    ProfileValidationError,
    delete_profile,
    get_profile,
    profile_category_dir,
    read_profile_document,
    sanitize_existing_graph_id,
    sanitize_existing_node_id,
    upsert_profile,
    validate_explicit_graph_id,
    validate_profile_id,
)
from .service_host import HostBoundService
from .shared import HTTPException


PROFILE_EXCLUDED_NODE_FIELDS = {
    *RESERVED_NODE_CONFIG_FIELDS,
    *RUNTIME_STATE_FIELDS,
    "schema",
    "_config_version",
    "pending_count",
}


def _profile_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProfileValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ProfileStorageError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _node_fields_from_config(config: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in config.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if key in PROFILE_EXCLUDED_NODE_FIELDS:
            continue
        fields[key] = copy.deepcopy(value)
    return fields


def _node_profile_config(config: dict[str, Any]) -> dict[str, Any]:
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
        "fields": _node_fields_from_config(config),
    }
    ui = config.get("ui")
    if isinstance(ui, dict):
        payload["ui"] = copy.deepcopy(ui)
    input_num = config.get("input_num")
    if input_num is not None:
        payload["input_num"] = input_num
    output_num = config.get("output_num")
    if output_num is not None:
        payload["output_num"] = output_num
    return payload


def _node_config_from_profile(profile_node: dict[str, Any], *, target_graph_id: str) -> dict[str, Any]:
    if not isinstance(profile_node, dict):
        raise ProfileValidationError("profile node config must be an object")
    node_id = str(profile_node.get("node_id") or "").strip()
    type_id = str(profile_node.get("type_id") or "").strip()
    if not node_id:
        raise ProfileValidationError("profile node config is missing node_id")
    if not type_id:
        raise ProfileValidationError(f"profile node {node_id} is missing type_id")
    fields = profile_node.get("fields")
    if fields is None:
        fields = {}
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
    input_num = profile_node.get("input_num")
    if input_num is not None:
        payload["input_num"] = input_num
    output_num = profile_node.get("output_num")
    if output_num is not None:
        payload["output_num"] = output_num
    for key, value in fields.items():
        if isinstance(key, str) and key.strip() and key not in PROFILE_EXCLUDED_NODE_FIELDS:
            payload[key] = copy.deepcopy(value)
    return payload


class ProfileApi(HostBoundService):
    def _agent_profile_dir(self) -> str:
        return profile_category_dir(AGENT_PROFILE_DIR)

    def _graph_profile_dir(self) -> str:
        return profile_category_dir(GRAPH_PROFILE_DIR)

    def list_agent_profiles(self):
        try:
            return read_profile_document(self._agent_profile_dir())
        except Exception as exc:
            raise _profile_error(exc)

    def delete_agent_profile(self, profile_id: str):
        try:
            safe_profile_id = validate_profile_id(profile_id)
            deleted = delete_profile(self._agent_profile_dir(), safe_profile_id)
        except Exception as exc:
            raise _profile_error(exc)
        if not deleted:
            raise HTTPException(status_code=404, detail="agent profile not found")
        return {"ok": True, "profile_id": safe_profile_id, "deleted": True}

    def save_agent_profile_from_node(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        try:
            graph_id = sanitize_existing_graph_id(self.graph_runtime, payload.get("graph_id"))
            node_id = sanitize_existing_node_id(self.graph_runtime, payload.get("node_id"))
            profile_id = validate_profile_id(payload.get("profile_id"))
        except Exception as exc:
            raise _profile_error(exc)

        config_path = self.graph_runtime._node_config_path(node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        try:
            cfg = node_config_service.read_strict(config_path)
            type_id = str(cfg.get("type_id") or "").strip()
            if not type_id:
                raise ProfileValidationError("node config is missing type_id")
            node_name = str(cfg.get("name") or node_id).strip() or node_id
            profile_name = str(payload.get("profile_name") or node_name or profile_id).strip() or profile_id
            profile = {
                "id": profile_id,
                "name": profile_name,
                "node_type_id": type_id,
                "source_graph_id": graph_id,
                "source_node_id": node_id,
                "node_name": node_name,
                "fields": _node_fields_from_config(cfg),
            }
            saved = upsert_profile(self._agent_profile_dir(), profile)
            return {"ok": True, "profile": saved}
        except Exception as exc:
            raise _profile_error(exc)

    def list_graph_profiles(self):
        try:
            return read_profile_document(self._graph_profile_dir())
        except Exception as exc:
            raise _profile_error(exc)

    def delete_graph_profile(self, profile_id: str):
        try:
            safe_profile_id = validate_profile_id(profile_id)
            deleted = delete_profile(self._graph_profile_dir(), safe_profile_id)
        except Exception as exc:
            raise _profile_error(exc)
        if not deleted:
            raise HTTPException(status_code=404, detail="graph profile not found")
        return {"ok": True, "profile_id": safe_profile_id, "deleted": True}

    def save_graph_profile_from_graph(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        try:
            graph_id = sanitize_existing_graph_id(self.graph_runtime, payload.get("graph_id"))
            profile_id = validate_profile_id(payload.get("profile_id"))
        except Exception as exc:
            raise _profile_error(exc)

        graph_dir = self.graph_runtime._graph_dir(graph_id)
        if not os.path.isdir(graph_dir) and graph_id != self.default_graph_id:
            raise HTTPException(status_code=404, detail="graph not found")
        try:
            graph_config = self.graph_runtime._read_graph_config(graph_id)
        except GraphConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        graph_profile = dict(graph_config or {})
        graph_profile["id"] = graph_id
        graph_profile["name"] = str(graph_profile.get("name") or graph_id)

        node_configs: list[dict[str, Any]] = []
        if os.path.isdir(graph_dir):
            for entry in sorted(os.listdir(graph_dir)):
                config_path = os.path.join(graph_dir, entry, "config.json")
                if not os.path.isfile(config_path):
                    continue
                try:
                    cfg = node_config_service.read_strict(config_path)
                except NodeConfigReadError as exc:
                    raise HTTPException(status_code=500, detail=str(exc))
                node_cfg = _node_profile_config(cfg)
                node_configs.append(node_cfg)

        graph_profile["nodes"] = [
            {
                "id": item["node_id"],
                "typeId": item["type_id"],
                "name": item.get("name") or item["node_id"],
                "ui": copy.deepcopy(item.get("ui") or {"x": 0, "y": 0}),
                "input_num": item.get("input_num"),
                "output_num": item.get("output_num"),
            }
            for item in node_configs
        ]

        profile_name = str(payload.get("profile_name") or graph_profile.get("name") or profile_id).strip() or profile_id
        try:
            saved = upsert_profile(
                self._graph_profile_dir(),
                {
                    "id": profile_id,
                    "name": profile_name,
                    "source_graph_id": graph_id,
                    "graph": graph_profile,
                    "node_configs": node_configs,
                },
            )
            return {"ok": True, "profile": saved}
        except Exception as exc:
            raise _profile_error(exc)

    def create_graph_from_profile(self, profile_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        try:
            safe_profile_id = validate_profile_id(profile_id)
            target_graph_id = validate_explicit_graph_id(self.graph_runtime, payload.get("graph_id"))
            profile = get_profile(self._graph_profile_dir(), safe_profile_id)
        except Exception as exc:
            raise _profile_error(exc)
        if profile is None:
            raise HTTPException(status_code=404, detail="graph profile not found")

        graphs_dir = runtime_paths._get_graphs_dir()
        graph_dir = os.path.join(graphs_dir, target_graph_id)
        if os.path.exists(graph_dir):
            raise HTTPException(status_code=409, detail="target graph id already exists")

        raw_graph = profile.get("graph")
        if not isinstance(raw_graph, dict):
            raise HTTPException(status_code=500, detail="graph profile graph must be an object")
        raw_node_configs = profile.get("node_configs")
        if not isinstance(raw_node_configs, list):
            raise HTTPException(status_code=500, detail="graph profile node_configs must be a list")

        graph = copy.deepcopy(raw_graph)
        graph["id"] = target_graph_id
        graph["name"] = target_graph_id
        for node in graph.get("nodes") or []:
            if isinstance(node, dict):
                node["graph_id"] = target_graph_id

        try:
            os.makedirs(graph_dir, exist_ok=False)
            graph_config = dict(graph)
            graph_config.pop("nodes", None)
            graph_config["id"] = target_graph_id
            graph_config["name"] = target_graph_id
            _write_graph_config(os.path.join(graph_dir, "config.json"), graph_config)

            for item in raw_node_configs:
                node_cfg = _node_config_from_profile(item, target_graph_id=target_graph_id)
                node_id = sanitize_existing_node_id(self.graph_runtime, node_cfg.get("node_id"))
                node_cfg["node_id"] = node_id
                node_cfg["graph_id"] = target_graph_id
                node_dir = os.path.join(graph_dir, node_id)
                os.makedirs(node_dir, exist_ok=False)
                node_config_service.create_or_replace(os.path.join(node_dir, "config.json"), node_cfg)

            self.graph_runtime._log_graph_event(
                target_graph_id,
                "graph_created_from_profile",
                profile_id=safe_profile_id,
                node_count=len(raw_node_configs),
            )
            self.graph_runtime._register_all_scheduled_nodes(force_rebuild=True)
            return {"ok": True, "graph": graph, "profile": profile}
        except HTTPException:
            shutil.rmtree(graph_dir, ignore_errors=True)
            raise
        except (ProfileValidationError, ProfileStorageError, NodeConfigWriteError, ValueError) as exc:
            shutil.rmtree(graph_dir, ignore_errors=True)
            raise _profile_error(exc)
        except Exception as exc:
            shutil.rmtree(graph_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=str(exc))


__all__ = ["ProfileApi"]
