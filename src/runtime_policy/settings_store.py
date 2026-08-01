from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from src.file_transaction import atomic_write_text
from src.runtime_policy.catalog import (
    CATALOG_RELATIVE_PATH,
    RuntimePolicyCatalog,
    _materialize_policy_prompts,
    _read_json_object,
)
from src.runtime_policy.contracts import (
    CodingRuntimePolicy,
    RuntimePolicyValidationError,
)
from src.workspace_settings import get_workspace_root


@dataclass(frozen=True)
class RuntimePolicySettingsEntry:
    policy_id: str
    source_path: str
    config: dict[str, Any]


class RuntimePolicySettingsStore:
    """Read and update the workspace-owned RuntimePolicy catalog sources."""

    def __init__(self, workspace_root: str | None = None) -> None:
        self.workspace_root = os.path.abspath(workspace_root or get_workspace_root())
        self.catalog_path = os.path.join(self.workspace_root, CATALOG_RELATIVE_PATH)
        self.config_root = os.path.dirname(self.catalog_path)

    def load(self) -> dict[str, Any]:
        catalog = RuntimePolicyCatalog.load(self.workspace_root)
        entries = [
            RuntimePolicySettingsEntry(
                policy_id=policy_id,
                source_path=os.path.relpath(item.source_path, self.workspace_root),
                config=_read_json_object(item.source_path),
            )
            for policy_id, item in sorted(catalog.policies.items())
        ]
        return {
            "schema_version": 1,
            "default_policy_id": catalog.default_policy_id,
            "catalog_path": os.path.relpath(catalog.source_path, self.workspace_root),
            "policies": [
                {
                    "policy_id": entry.policy_id,
                    "path": entry.source_path,
                    "config": entry.config,
                }
                for entry in entries
            ],
        }

    def update_default(self, policy_id: object) -> dict[str, Any]:
        selected_id = self._required_policy_id(policy_id)
        catalog = RuntimePolicyCatalog.load(self.workspace_root)
        if selected_id not in catalog.policies:
            available = ", ".join(sorted(catalog.policies))
            raise RuntimePolicyValidationError(
                f"unknown runtime policy {selected_id!r}; available policies: {available}."
            )
        source = _read_json_object(self.catalog_path)
        source["default_policy_id"] = selected_id
        atomic_write_text(
            self.catalog_path,
            json.dumps(source, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.load()

    def update_policy(self, policy_id: object, config: object) -> dict[str, Any]:
        selected_id = self._required_policy_id(policy_id)
        catalog = RuntimePolicyCatalog.load(self.workspace_root)
        catalog_entry = catalog.policies.get(selected_id)
        if catalog_entry is None:
            available = ", ".join(sorted(catalog.policies))
            raise RuntimePolicyValidationError(
                f"unknown runtime policy {selected_id!r}; available policies: {available}."
            )
        if not isinstance(config, dict):
            raise RuntimePolicyValidationError("runtime policy config must be an object.")

        materialized, _prompt_sources = _materialize_policy_prompts(
            config,
            policy_path=catalog_entry.source_path,
            config_root=self.config_root,
        )
        validated = CodingRuntimePolicy.from_payload(
            materialized,
            field=f"runtime policy {selected_id}",
        )
        if validated.policy_id != selected_id:
            raise RuntimePolicyValidationError(
                f"runtime policy {selected_id}.policy_id must equal its catalog id."
            )
        atomic_write_text(
            catalog_entry.source_path,
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.load()

    @staticmethod
    def _required_policy_id(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise RuntimePolicyValidationError("policy_id must be a non-empty string.")
        return value.strip()


__all__ = ["RuntimePolicySettingsStore"]
