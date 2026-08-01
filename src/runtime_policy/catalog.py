from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from src.runtime_policy.contracts import (
    CodingRuntimePolicy,
    RuntimePolicyValidationError,
)
from src.workspace_settings import get_workspace_root


CATALOG_RELATIVE_PATH = os.path.join("config", "runtimePolicies.json")


@dataclass(frozen=True)
class CatalogPolicy:
    policy: CodingRuntimePolicy
    source_path: str
    prompt_sources: dict[str, str]


class RuntimePolicyCatalog:
    def __init__(
        self,
        *,
        default_policy_id: str,
        policies: dict[str, CatalogPolicy],
        source_path: str,
    ) -> None:
        self.default_policy_id = default_policy_id
        self.policies = dict(policies)
        self.source_path = source_path

    @classmethod
    def load(cls, workspace_root: str | None = None) -> "RuntimePolicyCatalog":
        root = os.path.abspath(workspace_root or get_workspace_root())
        catalog_path = os.path.join(root, CATALOG_RELATIVE_PATH)
        payload = _read_json_object(catalog_path)
        _require_keys(
            payload,
            field="runtime policy catalog",
            required={"schema_version", "default_policy_id", "policies"},
        )
        if payload["schema_version"] != 1:
            raise RuntimePolicyValidationError("runtime policy catalog schema_version must be 1.")
        default_policy_id = _policy_id(
            payload["default_policy_id"],
            field="runtime policy catalog.default_policy_id",
        )
        entries = payload["policies"]
        if not isinstance(entries, dict) or not entries:
            raise RuntimePolicyValidationError(
                "runtime policy catalog.policies must be a non-empty object."
            )
        policies: dict[str, CatalogPolicy] = {}
        config_root = os.path.dirname(catalog_path)
        for raw_id, raw_relative_path in entries.items():
            policy_id = _policy_id(raw_id, field="runtime policy catalog policy id")
            if not isinstance(raw_relative_path, str) or not raw_relative_path.strip():
                raise RuntimePolicyValidationError(
                    f"runtime policy catalog.policies.{policy_id} must be a non-empty path."
                )
            policy_path = _safe_child_path(config_root, raw_relative_path)
            source_payload = _read_json_object(policy_path)
            materialized, prompt_sources = _materialize_policy_prompts(
                source_payload,
                policy_path=policy_path,
                config_root=config_root,
            )
            policy = CodingRuntimePolicy.from_payload(
                materialized,
                field=f"runtime policy {policy_id}",
            )
            if policy.policy_id != policy_id:
                raise RuntimePolicyValidationError(
                    f"runtime policy {policy_id}.policy_id must equal its catalog id."
                )
            policies[policy_id] = CatalogPolicy(
                policy=policy,
                source_path=policy_path,
                prompt_sources=prompt_sources,
            )
        if default_policy_id not in policies:
            raise RuntimePolicyValidationError(
                "runtime policy catalog.default_policy_id must reference a catalog policy."
            )
        return cls(
            default_policy_id=default_policy_id,
            policies=policies,
            source_path=catalog_path,
        )

    def get(self, policy_id: str | None = None) -> CatalogPolicy:
        selected_id = str(policy_id or self.default_policy_id).strip()
        policy = self.policies.get(selected_id)
        if policy is None:
            available = ", ".join(sorted(self.policies))
            raise RuntimePolicyValidationError(
                f"unknown runtime policy {selected_id!r}; available policies: {available}."
            )
        return policy

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "default_policy_id": self.default_policy_id,
            "policies": [
                {
                    "policy_id": item.policy.policy_id,
                    "version": item.policy.version,
                    "description": item.policy.description,
                }
                for item in sorted(self.policies.values(), key=lambda entry: entry.policy.policy_id)
            ],
        }


def _materialize_policy_prompts(
    payload: dict[str, Any],
    *,
    policy_path: str,
    config_root: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    data = json.loads(json.dumps(payload, ensure_ascii=False))
    prompt_sources: dict[str, str] = {}
    mappings = {
        "task_direction": {
            "core_prompt_file": "core_prompt",
            "code_prompt_file": "code_prompt",
        },
        "completion_review": {"prompt_file": "prompt"},
        "implementation_checkpoint": {"prompt_file": "prompt"},
        "context_compaction": {
            "gate_prompt_file": "gate_prompt",
            "retry_prompt_file": "retry_prompt",
        },
    }
    for section, fields in mappings.items():
        section_payload = data.get(section)
        if not isinstance(section_payload, dict):
            raise RuntimePolicyValidationError(
                f"{policy_path} field {section!r} must be an object."
            )
        for source_field, target_field in fields.items():
            raw_path = section_payload.pop(source_field, None)
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise RuntimePolicyValidationError(
                    f"{policy_path} field {section}.{source_field} must be a non-empty path."
                )
            prompt_path = _safe_child_path(config_root, raw_path)
            with open(prompt_path, "r", encoding="utf-8") as handle:
                prompt = handle.read().strip()
            if not prompt:
                raise RuntimePolicyValidationError(f"runtime policy prompt is empty: {prompt_path}.")
            section_payload[target_field] = prompt
            prompt_sources[f"{section}.{target_field}"] = os.path.relpath(prompt_path, config_root)
    return data, prompt_sources


def _read_json_object(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise RuntimePolicyValidationError(f"runtime policy file not found: {path}.")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimePolicyValidationError(f"invalid runtime policy JSON in {path}: {exc}.") from exc
    if not isinstance(payload, dict):
        raise RuntimePolicyValidationError(f"runtime policy file must contain an object: {path}.")
    return payload


def _require_keys(payload: dict[str, Any], *, field: str, required: set[str]) -> None:
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - required)
    if missing:
        raise RuntimePolicyValidationError(f"{field} is missing required fields: {', '.join(missing)}.")
    if unknown:
        raise RuntimePolicyValidationError(f"{field} has unknown fields: {', '.join(unknown)}.")


def _policy_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimePolicyValidationError(f"{field} must be a non-empty string.")
    text = value.strip()
    if any(not (char.isalnum() or char in {"-", "_", "."}) for char in text):
        raise RuntimePolicyValidationError(f"{field} contains invalid characters.")
    return text


def _safe_child_path(parent: str, relative_path: str) -> str:
    if os.path.isabs(relative_path):
        raise RuntimePolicyValidationError("runtime policy paths must be relative.")
    resolved_parent = os.path.abspath(parent)
    resolved = os.path.abspath(os.path.join(resolved_parent, relative_path))
    if os.path.commonpath([resolved_parent, resolved]) != resolved_parent:
        raise RuntimePolicyValidationError("runtime policy path escapes the config directory.")
    return resolved


__all__ = ["CatalogPolicy", "RuntimePolicyCatalog"]
