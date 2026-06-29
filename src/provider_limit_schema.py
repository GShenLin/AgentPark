from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from src import workspace_settings
from src.config_loader import ConfigLoader


PROVIDER_LIMIT_SCHEMA_VERSION = 1
REASONING_EFFORT_VALUES = ("minimal", "low", "medium", "high", "xhigh", "max", "auto")
THINKING_VALUES = ("enabled", "disabled", "auto")


@dataclass(frozen=True)
class ProbeResult:
    supported: bool
    reason: str = ""
    status_code: int = 0

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"supported": self.supported}
        if self.reason:
            payload["reason"] = self.reason
        if self.status_code:
            payload["status_code"] = self.status_code
        return payload


def provider_limit_path() -> str:
    explicit_path = str(os.environ.get(ConfigLoader.CONFIG_PATH_ENV) or "").strip()
    if explicit_path:
        return os.path.join(os.path.dirname(os.path.abspath(explicit_path)), "ProviderLimit.json")
    return os.path.join(workspace_settings.get_workspace_root(), "config", "ProviderLimit.json")


def read_provider_limit_file() -> dict[str, Any]:
    path = provider_limit_path()
    if not os.path.isfile(path):
        return {
            "schema_version": PROVIDER_LIMIT_SCHEMA_VERSION,
            "generated_at": "",
            "status": "finished",
            "completed_providers": 0,
            "total_providers": 0,
            "current_provider_id": "",
            "model_refresh_status": "finished",
            "model_refresh_completed_providers": 0,
            "model_refresh_total_providers": 0,
            "model_refresh_current_provider_id": "",
            "providers": {},
            "path": path,
        }
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"ProviderLimit.json must contain a top-level object: {path}")
    payload.setdefault("status", "finished")
    payload.setdefault("completed_providers", len(payload.get("providers") if isinstance(payload.get("providers"), dict) else {}))
    payload.setdefault("total_providers", payload.get("completed_providers", 0))
    payload.setdefault("current_provider_id", "")
    payload.setdefault("model_refresh_status", "finished")
    payload.setdefault("model_refresh_completed_providers", 0)
    payload.setdefault("model_refresh_total_providers", 0)
    payload.setdefault("model_refresh_current_provider_id", "")
    payload["path"] = path
    return payload
