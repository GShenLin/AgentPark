import json
import os

from src.file_transaction import atomic_write_text

from . import runtime_paths
from .profile_storage import (
    AGENT_PROFILE_DIR,
    get_profile,
    profile_category_dir,
    validate_profile_id,
)
from .service_host import HostBoundService
from .shared import HTTPException


class PasteAgentSettings(HostBoundService):
    DEFAULT_PROFILE_ID = "PasteAgent"

    def _paste_agent_config_path(self) -> str:
        return os.path.join(runtime_paths._get_runtime_root(), "config", "pastagent.json")

    def _default_paste_agent_config(self) -> dict:
        return {"profile_id": self.DEFAULT_PROFILE_ID}

    def _build_paste_agent_config(self, raw: dict | None) -> dict:
        default = self._default_paste_agent_config()
        payload = raw if isinstance(raw, dict) else {}
        profile_id = payload.get("profile_id", default["profile_id"])
        return {"profile_id": validate_profile_id(profile_id)}

    @staticmethod
    def _validate_agent_profile(profile_id: str) -> None:
        profile = get_profile(profile_category_dir(AGENT_PROFILE_DIR), profile_id)
        if profile is None:
            raise HTTPException(status_code=400, detail=f"agent profile not found: {profile_id}")
        node_type_id = str(profile.get("node_type_id") or "").strip()
        if node_type_id != "agent_node":
            raise HTTPException(
                status_code=400,
                detail=f"agent profile {profile_id} must use node_type_id agent_node",
            )

    def _write_paste_agent_config(self, config_payload: dict) -> str:
        config_path = self._paste_agent_config_path()
        if not isinstance(config_payload, dict):
            raise ValueError("pastagent config payload must be an object")
        atomic_write_text(config_path, json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n")
        return config_path

    def _read_paste_agent_config(self, ensure_exists: bool = True) -> dict:
        config_path = self._paste_agent_config_path()
        raw: dict = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"pastagent config contains invalid JSON: {config_path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
                ) from exc
            except OSError as exc:
                raise ValueError(f"failed to read pastagent config {config_path}: {type(exc).__name__}: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ValueError(f"pastagent config must be a JSON object: {config_path}")
            raw = loaded

        mapped = self._build_paste_agent_config(raw)
        if ensure_exists:
            needs_write = not os.path.exists(config_path)
            if not needs_write:
                needs_write = raw != mapped
            if needs_write:
                self._write_paste_agent_config(mapped)
        return mapped

    def get_paste_agent_config(self):
        try:
            config = self._read_paste_agent_config(ensure_exists=True)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to read pastagent config: {str(e)}")
        return {"config": config}

    def update_paste_agent_config(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        unknown_fields = sorted(set(payload) - {"profile_id"})
        if unknown_fields:
            raise HTTPException(
                status_code=400,
                detail=f"unknown pastagent config fields: {', '.join(unknown_fields)}",
            )

        current = self._read_paste_agent_config(ensure_exists=True)
        merged = dict(current)
        merged["profile_id"] = payload.get("profile_id", current["profile_id"])
        try:
            mapped = self._build_paste_agent_config(merged)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        self._validate_agent_profile(mapped["profile_id"])
        try:
            self._write_paste_agent_config(mapped)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to write pastagent config: {str(e)}")
        return {"ok": True, "config": mapped}
