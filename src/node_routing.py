from __future__ import annotations

import json
from typing import Any


def normalize_port_count(value: Any, default: int = 1) -> int:
    try:
        num = int(float(value))
    except Exception:
        num = default
    if num <= 0:
        return default
    return num


def normalize_port_index(value: Any) -> int | None:
    try:
        num = int(float(value))
    except Exception:
        return None
    if num < 0:
        return None
    return num


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def normalize_node_output(output: Any) -> dict:
    if not isinstance(output, dict):
        raise ValueError("Node output must be an object containing routes")

    raw_routes = output.get("routes")
    if not isinstance(raw_routes, list):
        raise ValueError("Node output must include routes: list")

    suppress_output = bool(output.get("suppress_output"))

    deduped_routes: list[dict] = []
    seen: set[int] = set()
    for item in raw_routes:
        if not isinstance(item, dict):
            continue
        idx = normalize_port_index(item.get("output_index"))
        if idx is None or idx in seen:
            continue
        if "payload" not in item:
            continue
        seen.add(idx)
        deduped_routes.append({"output_index": idx, "payload": _to_text(item.get("payload"))})
    if not deduped_routes and not suppress_output:
        raise ValueError("Node output routes must contain at least one valid route item")

    display_raw = output.get("display")
    if display_raw is None:
        display_raw = output.get("display_text")
    if display_raw is None and deduped_routes:
        display_raw = deduped_routes[0]["payload"]
    if display_raw is None:
        display_raw = ""
    display_text = _to_text(display_raw)

    return {
        "display_text": display_text,
        "routes": deduped_routes,
    }
