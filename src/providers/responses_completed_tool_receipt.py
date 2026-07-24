from __future__ import annotations

import hashlib
import json
from typing import Any

from src.providers.responses_input_items import build_responses_message_input_item
from src.tool.tool_call_protocol import ToolCallEnvelope


CHECKPOINT_PREFIX = "[AgentPark Completed Tool Context Checkpoint]"
CHECKPOINT_SCHEMA_VERSION = 2


class CompletedToolReceiptContractError(RuntimeError):
    """Raised when completed tool history cannot form an exact receipt."""


def completed_exchange_manifests(items: list[Any]) -> list[dict[str, Any]]:
    calls, outputs = tool_exchange_indexes(items, None)
    manifests = []
    for call_id in sorted(set(calls) & set(outputs), key=lambda item: calls[item][0]):
        if len(calls[call_id]) != 1 or len(outputs[call_id]) != 1:
            raise CompletedToolReceiptContractError(
                f"function-call exchange {call_id!r} is not unique"
            )
        call = items[calls[call_id][0]]
        output = items[outputs[call_id][0]]
        manifests.append(
            {
                "call_id": call_id,
                "name": str(call.get("name") or "").strip(),
                "arguments_chars": len(str(call.get("arguments") or "")),
                "arguments_sha256": sha256_value(call.get("arguments")),
                "output_chars": len(str(output.get("output") or "")),
                "output_sha256": sha256_value(output.get("output")),
            }
        )
    return manifests


def tool_exchange_indexes(
    items: list[Any],
    selected_ids: set[str] | None,
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    calls: dict[str, list[int]] = {}
    outputs: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type not in {"function_call", "function_call_output"}:
            continue
        call_id = str(item.get("call_id") or "").strip()
        if not call_id or (selected_ids is not None and call_id not in selected_ids):
            continue
        target = calls if item_type == "function_call" else outputs
        target.setdefault(call_id, []).append(index)
    return calls, outputs


def task_direction_snapshot(value: object) -> dict[str, Any]:
    payload = value.to_payload() if hasattr(value, "to_payload") else value
    if not isinstance(payload, dict):
        raise CompletedToolReceiptContractError(
            "task direction checkpoint must be an object"
        )
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
        raise CompletedToolReceiptContractError(
            "task direction checkpoint requires a positive revision"
        )
    if not isinstance(payload.get("state"), dict):
        raise CompletedToolReceiptContractError(
            "task direction checkpoint requires a structured state"
        )
    return json.loads(json.dumps(payload, ensure_ascii=False))


def build_receipt_item(
    *,
    checkpoint_call: ToolCallEnvelope,
    checkpoint_kind: str,
    context_checkpoint_policy: str | None,
    task_direction: dict[str, Any],
    include_task_direction_snapshot: bool,
    retired_exchanges: list[dict[str, Any]],
) -> dict[str, Any]:
    direction: dict[str, Any]
    if include_task_direction_snapshot:
        direction = {"mode": "snapshot", "value": task_direction}
    else:
        direction = {
            "mode": "unchanged",
            "revision": int(task_direction["revision"]),
        }
    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint": {
            "call_id": checkpoint_call.call_id,
            "tool": checkpoint_call.name,
            "kind": checkpoint_kind,
            "context_checkpoint_policy": str(context_checkpoint_policy or ""),
            "task_direction_revision": task_direction["revision"],
        },
        "newly_retired_exchanges": retired_exchanges,
        "task_direction": direction,
        "continuation_contract": _continuation_contract(checkpoint_kind),
    }
    text = CHECKPOINT_PREFIX + "\n" + json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return build_responses_message_input_item(
        role="developer",
        content=[{"type": "input_text", "text": text}],
    )


def is_checkpoint_receipt(item: object) -> bool:
    if not isinstance(item, dict) or str(item.get("type") or "").strip() != "message":
        return False
    content = item.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(part, dict)
        and str(part.get("text") or "").startswith(CHECKPOINT_PREFIX)
        for part in content
    )


def serialized_chars(items: list[Any]) -> int:
    return len(json.dumps(items, ensure_ascii=False, separators=(",", ":")))


def sha256_value(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _continuation_contract(checkpoint_kind: str) -> str:
    if checkpoint_kind == "workspace_handoff":
        boundary = (
            "The retired exchanges completed before an ordered "
            "task-direction-to-patch handoff."
        )
    elif checkpoint_kind == "pytest_verified":
        boundary = (
            "The retired exchanges are covered by a structured successful pytest "
            "completion after an installed workspace handoff."
        )
    elif checkpoint_kind == "analysis_verification":
        boundary = (
            "The retired exchanges precede a completed structured five-gate "
            "analysis verification."
        )
    else:
        raise CompletedToolReceiptContractError(
            f"unsupported completed tool checkpoint kind: {checkpoint_kind!r}"
        )
    return (
        boundary
        + " Treat the latest task-direction snapshot and current workspace as "
        "authoritative. The triggering function call and output remain complete in "
        "the next request. Re-read a narrow source region when exact retired output "
        "is required; do not reconstruct missing details."
    )


__all__ = [
    "CHECKPOINT_PREFIX",
    "CHECKPOINT_SCHEMA_VERSION",
    "CompletedToolReceiptContractError",
    "build_receipt_item",
    "completed_exchange_manifests",
    "is_checkpoint_receipt",
    "serialized_chars",
    "task_direction_snapshot",
    "tool_exchange_indexes",
]
