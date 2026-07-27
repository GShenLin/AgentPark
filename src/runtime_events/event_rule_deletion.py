from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from .event_models import CompiledRule, RuntimeEventRegistry
from .event_schema import EVENTS


def delete_configured_event(
    config: dict[str, Any],
    *,
    event: str,
    graph_id: str,
    node_id: str,
    handler_index: int | None,
) -> tuple[dict[str, Any], int]:
    safe_event = str(event or "").strip()
    safe_graph_id = str(graph_id or "").strip()
    safe_node_id = str(node_id or "").strip()
    if safe_event not in EVENTS:
        raise ValueError(f"unsupported event: {safe_event}")
    if not safe_graph_id or not safe_node_id:
        raise ValueError("graph_id and node_id are required")

    updated = deepcopy(config)
    rules = updated.get("rules")
    event_rules = rules.get(safe_event) if isinstance(rules, dict) else None
    graph_rules = event_rules.get(safe_graph_id) if isinstance(event_rules, dict) else None
    handlers = graph_rules.get(safe_node_id) if isinstance(graph_rules, dict) else None
    if not isinstance(handlers, list):
        raise ValueError("configured event not found")

    if handler_index is None:
        removed_handlers = len(handlers)
        graph_rules.pop(safe_node_id)
    else:
        if handler_index < 0 or handler_index >= len(handlers):
            raise ValueError("event handler not found")
        handlers.pop(handler_index)
        removed_handlers = 1
        if not handlers:
            graph_rules.pop(safe_node_id)

    if not graph_rules:
        event_rules.pop(safe_graph_id)
    if not event_rules:
        rules.pop(safe_event)
    return updated, removed_handlers


def remove_active_event(
    registry: RuntimeEventRegistry,
    *,
    config: dict[str, Any],
    event: str,
    graph_id: str,
    node_id: str,
    handler_index: int | None,
) -> RuntimeEventRegistry:
    key = (graph_id, node_id, event)
    next_index = dict(registry.rule_index)
    compiled = list(next_index.get(key, ()))
    if handler_index is None:
        next_index.pop(key, None)
    elif compiled:
        next_rules: list[CompiledRule] = []
        for rule in compiled:
            if rule.handler_index == handler_index:
                continue
            next_rules.append(
                replace(rule, handler_index=rule.handler_index - 1)
                if rule.handler_index > handler_index
                else rule
            )
        if next_rules:
            next_index[key] = tuple(next_rules)
        else:
            next_index.pop(key, None)
    return replace(registry, rule_index=next_index, config=deepcopy(config))
