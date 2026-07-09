from __future__ import annotations


def runtime_event_context_from_context(context: dict | None) -> list[str]:
    if not isinstance(context, dict):
        return []
    raw = context.get("runtime_event_context_fragments")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]
