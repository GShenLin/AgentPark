from __future__ import annotations

from copy import deepcopy
from typing import Any

from .event_rule_config import canonicalize_rules_payload, compile_rules_payload


SourceEventRules = dict[str, list[dict[str, Any]]]
RulesPayload = dict[str, dict[str, dict[str, list[dict[str, Any]]]]]


def export_source_event_rules(rules: RulesPayload, graph_id: str, node_id: str) -> SourceEventRules:
    output: SourceEventRules = {}
    for event, event_rules in canonicalize_rules_payload(rules).items():
        handlers = event_rules.get(graph_id, {}).get(node_id)
        if handlers is not None:
            output[event] = deepcopy(handlers)
    return output


def replace_source_event_rules(
    rules: RulesPayload,
    graph_id: str,
    node_id: str,
    source_event_rules: object,
) -> RulesPayload:
    safe_graph_id = str(graph_id or "").strip()
    safe_node_id = str(node_id or "").strip()
    if not safe_graph_id or not safe_node_id:
        raise ValueError("graph_id and node_id are required")
    if source_event_rules is None:
        source_event_rules = {}
    if not isinstance(source_event_rules, dict):
        raise ValueError("profile event_rules must be an object keyed by event")

    errors: list[dict[str, Any]] = []
    bound = compile_rules_payload(
        {
            event: {safe_graph_id: {safe_node_id: handlers}}
            for event, handlers in source_event_rules.items()
        },
        errors,
    )
    if errors:
        messages = "; ".join(str(item.get("message") or "invalid event rule") for item in errors)
        raise ValueError(messages)

    output = canonicalize_rules_payload(rules)
    for event in list(output):
        event_rules = output[event]
        graph_rules = event_rules.get(safe_graph_id)
        if graph_rules is None:
            continue
        graph_rules.pop(safe_node_id, None)
        if not graph_rules:
            event_rules.pop(safe_graph_id, None)
        if not event_rules:
            output.pop(event, None)

    for event, event_rules in bound.items():
        handlers = event_rules[safe_graph_id][safe_node_id]
        output.setdefault(event, {}).setdefault(safe_graph_id, {})[safe_node_id] = deepcopy(handlers)
    return output


def count_source_event_handlers(source_event_rules: SourceEventRules) -> int:
    return sum(len(handlers) for handlers in source_event_rules.values())


__all__ = [
    "SourceEventRules",
    "count_source_event_handlers",
    "export_source_event_rules",
    "replace_source_event_rules",
]
