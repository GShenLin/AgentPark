import json
import os
from typing import Iterable

from src.file_transaction import atomic_write_text

from . import runtime_paths
from .scheduled_node_registry import ScheduledNodeRegistration


SCHEDULE_INDEX_FILENAME = "schedule_index.json"
SCHEDULE_INDEX_SCHEMA_VERSION = 1


def schedule_index_path() -> str:
    return os.path.join(runtime_paths._get_graphs_dir(), SCHEDULE_INDEX_FILENAME)


def read_schedule_index(
    *,
    sanitize_graph_id,
    sanitize_node_id,
    node_config_path,
) -> list[ScheduledNodeRegistration] | None:
    path = schedule_index_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEDULE_INDEX_SCHEMA_VERSION:
        return None
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return None

    entries: list[ScheduledNodeRegistration] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            return None
        graph_id = sanitize_graph_id(raw.get("graph_id"))
        node_id = sanitize_node_id(raw.get("node_id"))
        type_id = str(raw.get("type_id") or "").strip()
        if type_id not in {"clock_node", "timer_trigger_node"}:
            return None
        if type_id == "clock_node":
            continue
        try:
            due_at = float(raw.get("due_at"))
        except Exception:
            return None
        config_path = node_config_path(node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            continue
        entries.append(
            ScheduledNodeRegistration(
                graph_id=graph_id,
                node_id=node_id,
                config_path=config_path,
                type_id=type_id,
                due_at=due_at,
            )
        )
    return entries


def write_schedule_index(entries: Iterable[ScheduledNodeRegistration]) -> None:
    path = schedule_index_path()
    payload = {
        "schemaVersion": SCHEDULE_INDEX_SCHEMA_VERSION,
        "entries": [
            {
                "graph_id": entry.graph_id,
                "node_id": entry.node_id,
                "type_id": entry.type_id,
                "due_at": entry.due_at,
            }
            for entry in sorted(entries, key=lambda item: (item.graph_id, item.node_id))
            if entry.type_id == "timer_trigger_node"
        ],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
