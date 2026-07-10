from __future__ import annotations

from typing import Any

from .event_schema import EVENTS


CompiledRulesPayload = dict[str, dict[str, dict[str, list[dict[str, Any]]]]]


def compile_rules_payload(raw: object, errors: list[dict[str, Any]]) -> CompiledRulesPayload:
    if raw is None:
        raw = {}
    if isinstance(raw, list):
        return _compile_legacy_rule_list(raw, errors)
    if not isinstance(raw, dict):
        errors.append(_error("", "rules", "rules must be an object keyed by event"))
        return {}

    output: CompiledRulesPayload = {}
    for event_raw, graph_rules_raw in raw.items():
        event = _text(event_raw)
        if event not in EVENTS:
            errors.append(_error("rules", event, f"unsupported event: {event}"))
            continue
        if not isinstance(graph_rules_raw, dict):
            errors.append(_error(f"rules.{event}", "", "event rules must be an object keyed by graph id"))
            continue
        event_rules: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for graph_raw, node_rules_raw in graph_rules_raw.items():
            graph_id = _text(graph_raw)
            if not graph_id:
                errors.append(_error(f"rules.{event}", "graph_id", "graph id is required"))
                continue
            if not isinstance(node_rules_raw, dict):
                errors.append(_error(f"rules.{event}.{graph_id}", "", "graph rules must be an object keyed by node id"))
                continue
            graph_rules: dict[str, list[dict[str, Any]]] = {}
            for node_raw, rule_raw in node_rules_raw.items():
                node_id = _text(node_raw)
                if not node_id:
                    errors.append(_error(f"rules.{event}.{graph_id}", "node_id", "node id is required"))
                    continue
                rules_for_node = _normalize_node_rules(rule_raw, f"rules.{event}.{graph_id}.{node_id}", errors)
                if rules_for_node:
                    graph_rules[node_id] = rules_for_node
            if graph_rules:
                event_rules[graph_id] = graph_rules
        if event_rules:
            output[event] = event_rules
    return output


def iter_rules(rules: CompiledRulesPayload) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event, event_rules in rules.items():
        for graph_id, graph_rules in event_rules.items():
            for node_id, node_rules in graph_rules.items():
                for local_index, rule in enumerate(node_rules):
                    output.append(
                        {
                            "event": event,
                            "graph_id": graph_id,
                            "node_id": node_id,
                            "rule": rule,
                            "path": f"rules.{event}.{graph_id}.{node_id}[{local_index}]",
                        }
                    )
    return output


def _compile_legacy_rule_list(raw: list[object], errors: list[dict[str, Any]]) -> CompiledRulesPayload:
    output: CompiledRulesPayload = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(_error(f"rules[{index}]", "", "rule must be an object", index))
            continue
        source = item.get("source")
        source = source if isinstance(source, dict) else {}
        event = _text(item.get("event"))
        graph_id = _text(source.get("graph_id"))
        node_id = _text(source.get("node_id"))
        if not event or not graph_id or not node_id:
            errors.append(_error(f"rules[{index}]", "rules", "legacy rule requires event and source graph_id/node_id", index))
            continue
        output.setdefault(event, {}).setdefault(graph_id, {}).setdefault(node_id, []).append(_rule_without_keys(item))
    return output


def _normalize_node_rules(raw: object, path: str, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        output: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                errors.append(_error(f"{path}[{index}]", "", "rule must be an object", index))
                continue
            output.append(_rule_without_keys(item))
        return output
    if isinstance(raw, dict):
        return [_rule_without_keys(raw)]
    errors.append(_error(path, "", "node rules must be a rule object or a list of rule objects"))
    return []


def _rule_without_keys(raw: dict[str, Any]) -> dict[str, Any]:
    output = dict(raw)
    output.pop("source", None)
    output.pop("event", None)
    return output


def _text(value: object) -> str:
    return str(value or "").strip()


def _error(path: str, field: str, message: str, rule_index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": "config/events.json", "field": field, "message": message}
    if path:
        payload["config_path"] = path
    if rule_index is not None:
        payload["rule_index"] = rule_index
    return payload
