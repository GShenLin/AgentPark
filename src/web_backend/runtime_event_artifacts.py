from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any

from src.file_transaction import atomic_write_text


RUNTIME_EVENT_ARTIFACT_DIRNAME = "runtime_event_artifacts"
RUNTIME_EVENT_ARTIFACT_THRESHOLD_BYTES = 32 * 1024
_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def compact_runtime_event_record(record: dict[str, Any], runtime_events_path: str) -> dict[str, Any]:
    """Move oversized nested fields out of a durable runtime-event JSONL row."""
    if not isinstance(record, dict):
        raise ValueError("runtime event record must be an object")
    if not runtime_events_path:
        return dict(record)
    node_dir = os.path.dirname(os.path.abspath(runtime_events_path))
    artifact_dir = os.path.join(node_dir, RUNTIME_EVENT_ARTIFACT_DIRNAME)
    return _compact_mapping(record, artifact_dir=artifact_dir, node_dir=node_dir, field_path="record")


def _compact_mapping(
    value: dict[str, Any],
    *,
    artifact_dir: str,
    node_dir: str,
    field_path: str,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for raw_key, child in value.items():
        key = str(raw_key)
        child_path = f"{field_path}.{key}"
        if isinstance(child, dict):
            output[key] = _compact_mapping(
                child,
                artifact_dir=artifact_dir,
                node_dir=node_dir,
                field_path=child_path,
            )
            continue
        serialized = _serialize_json(child)
        if len(serialized.encode("utf-8")) <= RUNTIME_EVENT_ARTIFACT_THRESHOLD_BYTES:
            output[key] = child
            continue
        reference = _write_artifact(
            child,
            serialized=serialized,
            artifact_dir=artifact_dir,
            node_dir=node_dir,
            field_path=child_path,
        )
        if key == "message" and isinstance(child, str):
            output[key] = f"[oversized runtime event message stored in {reference['artifact_path']}]"
            output["message_artifact"] = reference
        else:
            output[key] = reference
    return output


def _write_artifact(
    value: Any,
    *,
    serialized: str,
    artifact_dir: str,
    node_dir: str,
    field_path: str,
) -> dict[str, Any]:
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    safe_field = _SAFE_NAME_PATTERN.sub("_", field_path).strip("._")[-80:] or "field"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{stamp}_{uuid.uuid4().hex}_{safe_field}.json"
    artifact_path = os.path.join(artifact_dir, filename)
    atomic_write_text(artifact_path, serialized + "\n", encoding="utf-8")
    return {
        "type": "runtime_event_artifact",
        "artifact_path": os.path.relpath(artifact_path, node_dir).replace("\\", "/"),
        "sha256": digest,
        "json_chars": len(serialized),
    }


def _serialize_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"runtime event field is not JSON serializable: {exc}") from exc
