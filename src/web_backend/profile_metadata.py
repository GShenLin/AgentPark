from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


PROFILE_METADATA_SCHEMA_VERSION = 1
PROFILE_EVIDENCE_LEVELS = {"measured", "inferred", "experimental"}
PROFILE_AB_VARIANTS = {"A", "B"}


class ProfileMetadataValidationError(ValueError):
    pass


def validate_profile_metadata(value: object, *, field: str = "profile_metadata") -> dict[str, Any]:
    data = _strict_object(
        value,
        field=field,
        required={
            "schema_version",
            "task_family",
            "description",
            "provider_rationale",
            "evidence_level",
            "recommended_for",
            "avoid_for",
            "ab_test",
        },
    )
    if data["schema_version"] != PROFILE_METADATA_SCHEMA_VERSION:
        raise ProfileMetadataValidationError(f"{field}.schema_version must be 1")
    task_family = _identifier(data["task_family"], field=f"{field}.task_family")
    description = _non_empty_string(data["description"], field=f"{field}.description")
    provider_rationale = _non_empty_string(
        data["provider_rationale"],
        field=f"{field}.provider_rationale",
    )
    evidence_level = _non_empty_string(
        data["evidence_level"],
        field=f"{field}.evidence_level",
    )
    if evidence_level not in PROFILE_EVIDENCE_LEVELS:
        allowed = ", ".join(sorted(PROFILE_EVIDENCE_LEVELS))
        raise ProfileMetadataValidationError(
            f"{field}.evidence_level must be one of: {allowed}"
        )
    ab_test = _strict_object(
        data["ab_test"],
        field=f"{field}.ab_test",
        required={"experiment_id", "variant", "peer_profile_id"},
    )
    experiment_id = _identifier(
        ab_test["experiment_id"],
        field=f"{field}.ab_test.experiment_id",
    )
    variant = _non_empty_string(ab_test["variant"], field=f"{field}.ab_test.variant")
    if variant not in PROFILE_AB_VARIANTS:
        raise ProfileMetadataValidationError(f"{field}.ab_test.variant must be A or B")
    peer_profile_id = _profile_id(
        ab_test["peer_profile_id"],
        field=f"{field}.ab_test.peer_profile_id",
    )
    return {
        "schema_version": PROFILE_METADATA_SCHEMA_VERSION,
        "task_family": task_family,
        "description": description,
        "provider_rationale": provider_rationale,
        "evidence_level": evidence_level,
        "recommended_for": _string_list(
            data["recommended_for"],
            field=f"{field}.recommended_for",
        ),
        "avoid_for": _string_list(data["avoid_for"], field=f"{field}.avoid_for"),
        "ab_test": {
            "experiment_id": experiment_id,
            "variant": variant,
            "peer_profile_id": peer_profile_id,
        },
    }


def validated_profile_metadata_copy(profile: dict[str, Any]) -> dict[str, Any] | None:
    if "profile_metadata" not in profile:
        return None
    return copy.deepcopy(validate_profile_metadata(profile["profile_metadata"]))


def profile_ab_comparison_contract(profile: dict[str, Any]) -> dict[str, Any] | None:
    metadata = validated_profile_metadata_copy(profile)
    if metadata is None:
        return None
    raw_fields = profile.get("fields")
    if not isinstance(raw_fields, dict):
        raise ProfileMetadataValidationError("curated Profile fields must be an object")
    controlled_fields = {
        key: copy.deepcopy(value)
        for key, value in raw_fields.items()
        if key != "provider_id"
    }
    controlled_payload = {
        "node_type_id": profile.get("node_type_id"),
        "fields": controlled_fields,
        "event_rules": copy.deepcopy(profile.get("event_rules", {})),
    }
    canonical = json.dumps(
        controlled_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    ab_test = metadata["ab_test"]
    profile_id = _profile_id(profile.get("id"), field="profile.id")
    provider_id = _non_empty_string(
        raw_fields.get("provider_id"),
        field="profile.fields.provider_id",
    )
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "provider_id": provider_id,
        "task_family": metadata["task_family"],
        "experiment_id": ab_test["experiment_id"],
        "variant": ab_test["variant"],
        "peer_profile_id": ab_test["peer_profile_id"],
        "excluded_variable": "fields.provider_id",
        "controlled_configuration_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }


def _strict_object(value: object, *, field: str, required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileMetadataValidationError(f"{field} must be an object")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing:
        raise ProfileMetadataValidationError(
            f"{field} is missing required fields: {', '.join(missing)}"
        )
    if unknown:
        raise ProfileMetadataValidationError(
            f"{field} has unknown fields: {', '.join(unknown)}"
        )
    return dict(value)


def _non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileMetadataValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _identifier(value: object, *, field: str) -> str:
    text = _non_empty_string(value, field=field)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", text):
        raise ProfileMetadataValidationError(
            f"{field} must use lowercase letters, numbers, and single hyphens"
        )
    return text


def _profile_id(value: object, *, field: str) -> str:
    text = _non_empty_string(value, field=field)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ProfileMetadataValidationError(
            f"{field} must contain only letters, numbers, underscores, or hyphens"
        )
    return text


def _string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ProfileMetadataValidationError(f"{field} must be an array of strings")
    items: list[str] = []
    for index, item in enumerate(value):
        text = _non_empty_string(item, field=f"{field}[{index}]")
        if text in items:
            raise ProfileMetadataValidationError(f"{field} contains duplicate value {text!r}")
        items.append(text)
    return items


__all__ = [
    "PROFILE_AB_VARIANTS",
    "PROFILE_EVIDENCE_LEVELS",
    "PROFILE_METADATA_SCHEMA_VERSION",
    "ProfileMetadataValidationError",
    "profile_ab_comparison_contract",
    "validate_profile_metadata",
    "validated_profile_metadata_copy",
]
