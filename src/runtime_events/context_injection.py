from __future__ import annotations

from typing import TypedDict


class RuntimeEventContextFragment(TypedDict):
    role: str
    content: str


def runtime_event_context_from_context(context: dict | None) -> list[RuntimeEventContextFragment]:
    if not isinstance(context, dict):
        return []
    raw = context.get("runtime_event_context_fragments")
    if not isinstance(raw, list):
        return []
    output: list[RuntimeEventContextFragment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role and content:
            output.append({"role": role, "content": content})
    return output
