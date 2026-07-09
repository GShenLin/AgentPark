from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Any

from src.file_transaction import KeyedTransactionQueue
from src.file_transaction import atomic_write_text


SCHEMA_VERSION = 1
MEMORY_FILENAME = "operational_memory.json"
_OPERATIONAL_MEMORY_QUEUE = KeyedTransactionQueue()


class OperationalMemoryError(ValueError):
    pass


def load_operational_memory(path: str) -> dict[str, Any]:
    return _run_operational_memory_transaction(path, lambda: _load_operational_memory_unlocked(path))


def _load_operational_memory_unlocked(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {"schema_version": SCHEMA_VERSION, "memories": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise OperationalMemoryError(f"failed to read operational memory: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise OperationalMemoryError("operational memory file must contain an object")
    memories = data.get("memories")
    if not isinstance(memories, dict):
        memories = {}
    return {"schema_version": SCHEMA_VERSION, "memories": memories}


def save_operational_memory(path: str, data: dict[str, Any]) -> None:
    return _run_operational_memory_transaction(path, lambda: _save_operational_memory_unlocked(path, data))


def _save_operational_memory_unlocked(path: str, data: dict[str, Any]) -> None:
    if not path:
        raise OperationalMemoryError("operational memory path is empty")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "memories": data.get("memories") if isinstance(data.get("memories"), dict) else {},
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)


def record_operational_memory_entry(
    *,
    path: str,
    action: str,
    reason: str = "",
    kind: str = "",
    title: str = "",
    lesson: str = "",
    evidence: str = "",
    scope: dict[str, Any] | None = None,
    tool_name: str = "",
    error: str = "",
    command: str = "",
    avoid: list[Any] | None = None,
    prefer: list[Any] | None = None,
    confidence: str = "medium",
    key: str = "",
    resolve_key: str = "",
    memories: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _run_operational_memory_transaction(
        path,
        lambda: _record_operational_memory_entry_unlocked(
            path=path,
            action=action,
            reason=reason,
            kind=kind,
            title=title,
            lesson=lesson,
            evidence=evidence,
            scope=scope,
            tool_name=tool_name,
            error=error,
            command=command,
            avoid=avoid,
            prefer=prefer,
            confidence=confidence,
            key=key,
            resolve_key=resolve_key,
            memories=memories,
        ),
    )


def _record_operational_memory_entry_unlocked(
    *,
    path: str,
    action: str,
    reason: str = "",
    kind: str = "",
    title: str = "",
    lesson: str = "",
    evidence: str = "",
    scope: dict[str, Any] | None = None,
    tool_name: str = "",
    error: str = "",
    command: str = "",
    avoid: list[Any] | None = None,
    prefer: list[Any] | None = None,
    confidence: str = "medium",
    key: str = "",
    resolve_key: str = "",
    memories: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(action, str):
        raise OperationalMemoryError("action must be upsert, replace, skip, or resolve")
    requested_action = action.strip()
    if requested_action not in {"upsert", "replace", "skip", "resolve"}:
        raise OperationalMemoryError("action must be upsert, replace, skip, or resolve")

    reason_text = _required_text(reason, "reason")
    if requested_action == "skip":
        return {"ok": True, "action": "skip", "reason": reason_text}

    data = _load_operational_memory_unlocked(path)
    stored_memories = data["memories"]
    now = _now_text()

    if requested_action == "replace":
        if not isinstance(memories, dict):
            raise OperationalMemoryError("replace requires memories object")
        normalized = _normalize_replacement_memories(memories, now)
        data["memories"] = normalized
        _save_operational_memory_unlocked(path, data)
        return {
            "ok": True,
            "action": "replace",
            "count": len(normalized),
            "reason": reason_text,
        }

    if requested_action == "resolve":
        target_key = str(resolve_key or key or "").strip()
        if not target_key:
            raise OperationalMemoryError("resolve requires key or resolve_key")
        item = stored_memories.get(target_key)
        if not isinstance(item, dict):
            return {"ok": True, "action": "resolve", "status": "not_found", "key": target_key}
        item["status"] = "resolved"
        item["resolved_at"] = now
        item["resolve_reason"] = reason_text
        stored_memories[target_key] = item
        _save_operational_memory_unlocked(path, data)
        return {"ok": True, "action": "resolve", "status": "resolved", "key": target_key}

    kind_text = _required_text(kind, "kind")
    title_text = _required_text(title, "title")
    lesson_text = _required_text(lesson, "lesson")
    evidence_text = _required_text(evidence, "evidence")
    scope_obj = scope if isinstance(scope, dict) else {}
    tool_text = str(tool_name or "").strip()
    key_text = str(key or "").strip() or build_memory_key(
        scope=scope_obj,
        kind=kind_text,
        tool_name=tool_text,
        title=title_text,
    )

    existing = stored_memories.get(key_text)
    if not isinstance(existing, dict):
        existing = {
            "key": key_text,
            "first_seen_at": now,
            "count": 0,
        }

    existing.update(
        {
            "kind": kind_text,
            "scope": scope_obj,
            "tool_name": tool_text,
            "title": title_text,
            "lesson": lesson_text,
            "evidence": evidence_text,
            "avoid": _string_list(avoid),
            "prefer": _string_list(prefer),
            "confidence": _validate_confidence(confidence),
            "status": "active",
            "last_seen_at": now,
            "reason": reason_text,
        }
    )
    existing["count"] = int(existing.get("count") or 0) + 1
    samples = existing.get("failure_samples")
    if not isinstance(samples, list):
        samples = []
    sample = _failure_sample(tool_name=tool_text, command=command, error=error)
    if sample:
        samples.append(sample)
    existing["failure_samples"] = samples[-3:]

    stored_memories[key_text] = existing
    _save_operational_memory_unlocked(path, data)
    return {"ok": True, "action": "upsert", "key": key_text, "count": existing["count"]}


def operational_memory_snapshot(path: str, *, max_chars: int = 12000) -> str:
    try:
        data = load_operational_memory(path)
    except Exception as exc:
        data = {"schema_version": SCHEMA_VERSION, "memories": {}, "read_error": f"{type(exc).__name__}: {exc}"}
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    if len(text) > max_chars:
        return text[: max(0, max_chars - 3)].rstrip() + "..."
    return text


def build_operational_memory_summary(path: str, *, max_items: int = 5, max_chars: int = 2000) -> str:
    data = load_operational_memory(path)
    items = [
        item
        for item in data.get("memories", {}).values()
        if isinstance(item, dict) and str(item.get("status") or "active") == "active"
    ]
    if not items:
        return ""
    items.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
    lines = ["Operational memory for this node:"]
    for item in items[:max(1, int(max_items or 1))]:
        title = str(item.get("title") or "").strip()
        lesson = str(item.get("lesson") or "").strip()
        prefer = ", ".join(_string_list(item.get("prefer")))
        avoid = ", ".join(_string_list(item.get("avoid")))
        line = f"- {title}: {lesson}" if title else f"- {lesson}"
        if prefer:
            line += f" Prefer: {prefer}."
        if avoid:
            line += f" Avoid: {avoid}."
        lines.append(line)
    summary = "\n".join(lines).strip()
    if len(summary) > max_chars:
        return summary[: max(0, max_chars - 3)].rstrip() + "..."
    return summary


def build_memory_key(*, scope: dict[str, Any], kind: str, tool_name: str, title: str) -> str:
    scope_text = json.dumps(scope if isinstance(scope, dict) else {}, ensure_ascii=False, sort_keys=True)
    raw = "|".join([scope_text, str(kind or ""), str(tool_name or ""), str(title or "")])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(title or "").strip().lower()).strip("_")[:48]
    return f"{slug or 'memory'}:{digest}"


def _normalize_replacement_memories(memories: dict[str, Any], now: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for raw_key, raw_item in memories.items():
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        key = str(item.get("key") or raw_key or "").strip()
        if not key:
            key = build_memory_key(
                scope=item.get("scope") if isinstance(item.get("scope"), dict) else {},
                kind=str(item.get("kind") or "tool_limitation"),
                tool_name=str(item.get("tool_name") or ""),
                title=str(item.get("title") or "operational memory"),
            )
        item["key"] = key
        item["kind"] = str(item.get("kind") or "tool_limitation").strip()
        item["scope"] = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        item["tool_name"] = str(item.get("tool_name") or "").strip()
        item["title"] = str(item.get("title") or "").strip()
        item["lesson"] = str(item.get("lesson") or "").strip()
        item["evidence"] = str(item.get("evidence") or "").strip()
        item["avoid"] = _string_list(item.get("avoid"))
        item["prefer"] = _string_list(item.get("prefer"))
        item["confidence"] = _validate_confidence(item.get("confidence"))
        status = str(item.get("status") or "active").strip()
        if status not in {"active", "resolved"}:
            raise OperationalMemoryError(f"invalid operational memory status for {key}: {status}")
        item["status"] = status
        item["first_seen_at"] = str(item.get("first_seen_at") or now)
        item["last_seen_at"] = str(item.get("last_seen_at") or now)
        try:
            item["count"] = max(0, int(item.get("count") or 0))
        except Exception:
            item["count"] = 0
        samples = item.get("failure_samples")
        item["failure_samples"] = samples[-3:] if isinstance(samples, list) else []
        output[key] = item
    return output


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OperationalMemoryError(f"{field_name} is required")
    return text


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    output = []
    for item in value:
        text = str(item or "").strip()
        if text:
            output.append(text)
    return output[:10]


def _validate_confidence(value: object) -> str:
    if value is None:
        return "medium"
    if not isinstance(value, str):
        raise OperationalMemoryError("confidence must be low, medium, or high")
    text = value.strip()
    if text not in {"low", "medium", "high"}:
        raise OperationalMemoryError("confidence must be low, medium, or high")
    return text


def _failure_sample(*, tool_name: str, command: str, error: str) -> dict[str, str]:
    sample = {}
    if tool_name:
        sample["tool_name"] = tool_name[:120]
    if command:
        sample["command"] = command[:500]
    if error:
        sample["error"] = error[:1000]
    if sample:
        sample["seen_at"] = _now_text()
    return sample


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _run_operational_memory_transaction(path: str, func):
    return _OPERATIONAL_MEMORY_QUEUE.run(path, func)
