from __future__ import annotations

from typing import Any


EVENT_NAMES: tuple[str, ...] = (
    "OnInput",
    "ToolFailure",
    "RuntimeNotice",
    "NetError",
    "WorkPersisted",
    "WorkFailed",
)

ACTION_NAMES: tuple[str, ...] = (
    "context.produce",
    "notice.write",
    "node.dispatch",
)

TTL_NAMES: tuple[str, ...] = ("current_run", "next_turn", "persistent")
PRIORITY_NAMES: tuple[str, ...] = ("low", "normal", "high")

EVENTS = frozenset(EVENT_NAMES)
ACTIONS = frozenset(ACTION_NAMES)
TTLS = frozenset(TTL_NAMES)
PRIORITIES = frozenset(PRIORITY_NAMES)


def runtime_event_schema() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "events": list(EVENT_NAMES),
        "actions": list(ACTION_NAMES),
        "ttls": list(TTL_NAMES),
        "priorities": list(PRIORITY_NAMES),
        "rules_shape": "rules[event][graph_id][node_id] = Rule[]",
        "max_enabled_rules_per_source_node": 50,
    }
