from __future__ import annotations

import os
from typing import Any

from src.companion_inbox import deliver_companion_notice


def notify_companion_about_operational_memory(
    *,
    agent: object,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    if not _should_notify_companion(arguments, result):
        return False
    notice = build_operational_memory_notice(agent=agent, arguments=arguments, result=result)
    if _is_companion_self_notice(notice):
        return False
    if not _has_node_identity(notice):
        return False
    notifier = getattr(agent, "_aitools_companion_notifier", None)
    try:
        if callable(notifier):
            notifier(notice)
            return True
        return deliver_companion_notice(notice)
    except Exception:
        return False


def build_operational_memory_notice(
    *,
    agent: object,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    args = dict(arguments if isinstance(arguments, dict) else {})
    payload = dict(result if isinstance(result, dict) else {})
    memory_path = str(getattr(agent, "current_memory_path", "") or "").strip()
    fallback_graph_id, fallback_node_id = _identity_from_memory_path(memory_path)
    return {
        "type": "operational_memory_notice",
        "source": {
            "graph_id": _agent_attr(agent, "_aitools_graph_id", "graph_id") or fallback_graph_id,
            "node_id": _agent_attr(agent, "_aitools_node_id", "node_instance_id", "agent_id", "node_id")
            or fallback_node_id,
            "node_type_id": _agent_attr(agent, "_aitools_node_type_id", "node_type_id"),
            "provider": str(getattr(agent, "provider_name", "") or "").strip(),
            "memory_path": memory_path,
        },
        "issue": {
            "tool_name": str(args.get("tool_name") or "").strip(),
            "error": str(args.get("error") or "").strip(),
            "command": str(args.get("command") or "").strip(),
            "evidence": str(args.get("evidence") or "").strip(),
            "title": str(args.get("title") or "").strip(),
            "reason": str(args.get("reason") or "").strip(),
            "scope": args.get("scope") if isinstance(args.get("scope"), dict) else {},
        },
        "memory": {
            "action": str(payload.get("action") or args.get("action") or "").strip(),
            "key": str(payload.get("key") or args.get("key") or args.get("resolve_key") or "").strip(),
            "title": str(args.get("title") or "").strip(),
            "lesson": str(args.get("lesson") or args.get("conclusion") or "").strip(),
            "kind": str(args.get("kind") or "").strip(),
            "confidence": str(args.get("confidence") or "").strip(),
            "result": payload,
        },
    }


def _record_result_ok(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("ok") is True:
        return True
    return str(result.get("status") or "").strip().lower() in {"success", "completed"}


def _should_notify_companion(arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if not _record_result_ok(result):
        return False
    payload = result if isinstance(result, dict) else {}
    args = arguments if isinstance(arguments, dict) else {}
    action = str(payload.get("action") or args.get("action") or "").strip().lower()
    return action != "skip"


def _has_node_identity(notice: dict[str, Any]) -> bool:
    source = notice.get("source") if isinstance(notice, dict) else None
    if not isinstance(source, dict):
        return False
    return bool(str(source.get("node_id") or "").strip())


def _is_companion_self_notice(notice: dict[str, Any]) -> bool:
    source = notice.get("source") if isinstance(notice, dict) else None
    if not isinstance(source, dict):
        return False
    graph_id = str(source.get("graph_id") or "").strip()
    node_id = str(source.get("node_id") or "").strip()
    return graph_id == "companion" and node_id == "companion"


def _agent_attr(agent: object, *names: str) -> str:
    for name in names:
        text = str(getattr(agent, name, "") or "").strip()
        if text:
            return text
    return ""


def _identity_from_memory_path(memory_path: str) -> tuple[str, str]:
    path = os.path.normpath(str(memory_path or "").strip())
    if not path:
        return "", ""
    filename = os.path.basename(path).lower()
    if filename != "memory.md":
        return "", ""
    node_dir = os.path.basename(os.path.dirname(path))
    graph_dir = os.path.basename(os.path.dirname(os.path.dirname(path)))
    if not node_dir:
        return "", ""
    if node_dir == "companion":
        return "companion", "companion"
    if graph_dir and graph_dir not in {"memories", "agents"}:
        return graph_dir, node_dir
    return "", node_dir
