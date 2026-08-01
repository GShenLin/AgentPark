from __future__ import annotations

from copy import deepcopy

from src.message_protocol import normalize_envelope


BOARD_OUTPUT_RESOURCE_LIMIT = 4
_RESOURCE_FIELDS = ("id", "uri", "kind", "mime", "name", "source")


def project_output_resources(
    message: object,
    *,
    limit: int = BOARD_OUTPUT_RESOURCE_LIMIT,
) -> list[dict]:
    envelope = normalize_envelope(message, default_role="assistant")
    resources: list[dict] = []
    for part in envelope.get("parts") or []:
        if not isinstance(part, dict) or part.get("type") != "resource":
            continue
        raw_resource = part.get("resource")
        if not isinstance(raw_resource, dict):
            continue
        uri = str(raw_resource.get("uri") or "").strip()
        if not uri:
            continue
        resource = {
            key: deepcopy(raw_resource[key])
            for key in _RESOURCE_FIELDS
            if key in raw_resource
        }
        resource["uri"] = uri
        resources.append({"type": "resource", "resource": resource})
        if len(resources) >= limit:
            break
    return resources


__all__ = ["BOARD_OUTPUT_RESOURCE_LIMIT", "project_output_resources"]
