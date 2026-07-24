from __future__ import annotations

import copy
import os
import shutil
from typing import Any

from .node_config_service import node_config_service
from .profile_node_config import PROFILE_EXCLUDED_NODE_FIELDS, node_fields_from_config
from .profile_storage import (
    AGENT_PROFILE_DIR,
    ProfileValidationError,
    delete_profile,
    get_profile,
    profile_category_dir,
    read_profile_document,
    sanitize_existing_graph_id,
    sanitize_existing_node_id,
    upsert_profile,
    validate_profile_id,
)
from .shared import HTTPException


class AgentProfileApi:
    def _agent_profile_dir(self) -> str:
        return profile_category_dir(AGENT_PROFILE_DIR)

    def list_agent_profiles(self):
        try:
            return read_profile_document(self._agent_profile_dir())
        except Exception as exc:
            raise self._profile_error(exc)

    def update_agent_profile(self, profile_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        try:
            safe_profile_id = validate_profile_id(profile_id)
            existing = get_profile(self._agent_profile_dir(), safe_profile_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="agent profile not found")
            profile = self._profile_from_editor_payload(safe_profile_id, existing, payload)
            saved = upsert_profile(self._agent_profile_dir(), profile)
            return {"ok": True, "profile": saved}
        except HTTPException:
            raise
        except Exception as exc:
            raise self._profile_error(exc)

    @staticmethod
    def _profile_from_editor_payload(
        profile_id: str,
        existing: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        allowed_payload_keys = {"node_profiler", "instruction", "system_prompt"}
        unknown_payload_keys = sorted(set(payload) - allowed_payload_keys)
        if unknown_payload_keys:
            raise ProfileValidationError(
                f"unknown editor payload fields: {', '.join(unknown_payload_keys)}"
            )

        node_profiler = payload.get("node_profiler")
        if not isinstance(node_profiler, dict):
            raise ProfileValidationError("node_profiler must be an object")
        allowed_profile_keys = {
            "name",
            "node_type_id",
            "source_graph_id",
            "source_node_id",
            "node_name",
            "fields",
            "event_rules",
        }
        unknown_profile_keys = sorted(set(node_profiler) - allowed_profile_keys)
        if unknown_profile_keys:
            raise ProfileValidationError(
                f"unknown node_profiler fields: {', '.join(unknown_profile_keys)}"
            )

        name = str(node_profiler.get("name") or "").strip()
        node_type_id = str(node_profiler.get("node_type_id") or "").strip()
        fields = node_profiler.get("fields")
        event_rules = node_profiler.get("event_rules", {})
        instruction = payload.get("instruction")
        system_prompt = payload.get("system_prompt")
        if not name:
            raise ProfileValidationError("node_profiler.name is required")
        if not node_type_id:
            raise ProfileValidationError("node_profiler.node_type_id is required")
        if not isinstance(fields, dict):
            raise ProfileValidationError("node_profiler.fields must be an object")
        if "instruction" in fields or "system_prompt" in fields:
            raise ProfileValidationError(
                "instruction and system_prompt must use their dedicated editor fields"
            )
        if not isinstance(event_rules, dict):
            raise ProfileValidationError("node_profiler.event_rules must be an object")
        if not isinstance(instruction, str):
            raise ProfileValidationError("instruction must be a string")
        if not isinstance(system_prompt, str):
            raise ProfileValidationError("system_prompt must be a string")

        next_fields = copy.deepcopy(fields)
        next_fields["instruction"] = instruction
        next_fields["system_prompt"] = system_prompt
        next_profile: dict[str, Any] = {
            "id": profile_id,
            "name": name,
            "node_type_id": node_type_id,
            "fields": next_fields,
            "event_rules": copy.deepcopy(event_rules),
            "created_at": existing.get("created_at"),
        }
        for key in ("source_graph_id", "source_node_id", "node_name"):
            value = node_profiler.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ProfileValidationError(f"node_profiler.{key} must be a string")
            next_profile[key] = value
        return next_profile

    def delete_agent_profile(self, profile_id: str):
        try:
            safe_profile_id = validate_profile_id(profile_id)
            deleted = delete_profile(self._agent_profile_dir(), safe_profile_id)
        except Exception as exc:
            raise self._profile_error(exc)
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
            raise self._profile_error(exc)

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
                "fields": node_fields_from_config(cfg),
                "event_rules": self.runtime_events.export_source_event_rules(graph_id, node_id),
            }
            saved = upsert_profile(self._agent_profile_dir(), profile)
            return {"ok": True, "profile": saved}
        except Exception as exc:
            raise self._profile_error(exc)

    def create_agent_node_from_profile(self, profile_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        try:
            safe_profile_id = validate_profile_id(profile_id)
            graph_id = sanitize_existing_graph_id(self.graph_runtime, payload.get("graph_id"))
            node_id = sanitize_existing_node_id(self.graph_runtime, payload.get("node_id"))
            profile = get_profile(self._agent_profile_dir(), safe_profile_id)
        except Exception as exc:
            raise self._profile_error(exc)
        if profile is None:
            raise HTTPException(status_code=404, detail="agent profile not found")
        return self._create_agent_node_from_profile(
            safe_profile_id,
            profile,
            graph_id=graph_id,
            node_id=node_id,
            name=payload.get("name"),
            ui=payload.get("ui"),
        )

    def load_agent_profile_into_node(self, profile_id: str, payload: dict):
        """Apply profile fields and events to an existing node without changing its identity."""
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        try:
            safe_profile_id = validate_profile_id(profile_id)
            graph_id = sanitize_existing_graph_id(self.graph_runtime, payload.get("graph_id"))
            node_id = sanitize_existing_node_id(self.graph_runtime, payload.get("node_id"))
            profile = get_profile(self._agent_profile_dir(), safe_profile_id)
        except Exception as exc:
            raise self._profile_error(exc)
        if profile is None:
            raise HTTPException(status_code=404, detail="agent profile not found")

        config_path = self.graph_runtime._node_config_path(node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")

        fields = profile.get("fields")
        event_rules = profile.get("event_rules", {})
        if not isinstance(fields, dict):
            raise HTTPException(status_code=400, detail=f"agent profile {safe_profile_id} fields must be an object")
        if not isinstance(event_rules, dict):
            raise HTTPException(
                status_code=400,
                detail=f"agent profile {safe_profile_id} event_rules must be an object",
            )

        try:
            current_config = node_config_service.read_strict(config_path)
            current_type_id = str(current_config.get("type_id") or "").strip()
            profile_type_id = str(profile.get("node_type_id") or "").strip()
            if not profile_type_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"agent profile {safe_profile_id} is missing node_type_id",
                )
            if profile_type_id != current_type_id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"agent profile node_type_id {profile_type_id} does not match "
                        f"target node type_id {current_type_id}"
                    ),
                )
            before_events = self.runtime_events.export_source_event_rules(graph_id, node_id)
            result = node_config_service.apply_webui_payload(
                config_path,
                {"fields": copy.deepcopy(fields)},
                init_clock=lambda type_id, cfg: self.graph_runtime._try_init_node_config(
                    type_id, cfg, graph_id, node_id
                ),
                sync_ports=lambda type_id, cfg: self.graph_runtime._sync_node_config_ports(
                    type_id, cfg, graph_id, node_id
                ),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise self._profile_error(exc)

        try:
            event_result = self.runtime_events.replace_source_event_rules(graph_id, node_id, event_rules)
        except Exception as exc:
            rollback_errors: list[str] = []
            try:
                node_config_service.write(config_path, result.before)
            except Exception as rollback_exc:
                rollback_errors.append(f"config rollback failed: {rollback_exc}")
            try:
                self.runtime_events.replace_source_event_rules(graph_id, node_id, before_events)
            except Exception as rollback_exc:
                rollback_errors.append(f"event rollback failed: {rollback_exc}")
            detail = str(exc)
            if rollback_errors:
                detail = f"{detail}; {'; '.join(rollback_errors)}"
            raise HTTPException(status_code=500, detail=detail)

        self.graph_runtime._refresh_scheduled_node(graph_id, node_id)
        return {
            "ok": True,
            "profile_id": safe_profile_id,
            "graph_id": graph_id,
            "node_id": node_id,
            "config": result.to_payload(),
            "event_rules": event_result,
        }

    def _create_agent_node_from_profile(
        self,
        profile_id: str,
        profile: dict[str, Any],
        *,
        graph_id: str,
        node_id: str,
        name: object = None,
        ui: object = None,
        extra_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        type_id = str(profile.get("node_type_id") or "").strip()
        fields = profile.get("fields")
        event_rules = profile.get("event_rules", {})
        if not type_id:
            raise ProfileValidationError(f"agent profile {profile_id} is missing node_type_id")
        if not isinstance(fields, dict):
            raise ProfileValidationError(f"agent profile {profile_id} fields must be an object")
        if not isinstance(event_rules, dict):
            raise ProfileValidationError(f"agent profile {profile_id} event_rules must be an object")
        if ui is not None and not isinstance(ui, dict):
            raise ProfileValidationError("ui must be an object")
        node_dir = self.graph_runtime._node_dir(graph_id, node_id)
        if os.path.exists(node_dir):
            raise HTTPException(status_code=409, detail="target node id already exists")

        created = False
        try:
            result = self.node_ops.create_node_instance(
                {
                    "node_id": node_id,
                    "type_id": type_id,
                    "name": str(name or profile.get("node_name") or profile.get("name") or node_id).strip() or node_id,
                    "graph_id": graph_id,
                    "ui": copy.deepcopy(ui) if isinstance(ui, dict) else None,
                }
            )
            created = True
            config_path = str(result.get("config_path") or "")
            cfg = node_config_service.read_strict(config_path)
            for key, value in fields.items():
                if isinstance(key, str) and key.strip() and key not in PROFILE_EXCLUDED_NODE_FIELDS:
                    cfg[key] = copy.deepcopy(value)
            if isinstance(extra_config, dict):
                cfg.update(copy.deepcopy(extra_config))
            node_config_service.write(config_path, cfg)
            event_result = self.runtime_events.replace_source_event_rules(graph_id, node_id, event_rules)
            self.graph_runtime._refresh_scheduled_node(graph_id, node_id)
            return {**result, "profile_id": profile_id, "event_rules": event_result}
        except HTTPException:
            if created:
                self._rollback_profile_node(graph_id, node_id, node_dir)
            raise
        except Exception as exc:
            if created:
                self._rollback_profile_node(graph_id, node_id, node_dir)
            raise self._profile_error(exc)

    def _rollback_profile_node(self, graph_id: str, node_id: str, node_dir: str) -> None:
        try:
            self.runtime_events.remove_source_rules(graph_id, node_id)
        except Exception:
            pass
        self.graph_runtime._unregister_scheduled_node(graph_id, node_id)
        shutil.rmtree(node_dir, ignore_errors=True)


__all__ = ["AgentProfileApi"]
