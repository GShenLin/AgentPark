from __future__ import annotations

from typing import Any

from .event_schema import EVENTS


CompiledRulesPayload = dict[str, dict[str, dict[str, list[dict[str, Any]]]]]


def compile_rules_payload(raw: object, errors: list[dict[str, Any]]) -> CompiledRulesPayload:
    if raw is None:
        raw = {}
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
            for node_raw, handlers_raw in node_rules_raw.items():
                node_id = _text(node_raw)
                path = f"rules.{event}.{graph_id}.{node_id}"
                if not node_id:
                    errors.append(_error(f"rules.{event}.{graph_id}", "node_id", "node id is required"))
                    continue
                if not isinstance(handlers_raw, list):
                    errors.append(_error(path, "", "node event handlers must be a list"))
                    continue
                handlers: list[dict[str, Any]] = []
                for index, handler_raw in enumerate(handlers_raw):
                    if not isinstance(handler_raw, dict):
                        errors.append(_error(f"{path}[{index}]", "", "handler must be an object", index))
                        continue
                    handlers.append(dict(handler_raw))
                graph_rules[node_id] = handlers
            if graph_rules:
                event_rules[graph_id] = graph_rules
        if event_rules:
            output[event] = event_rules
    return output


def canonicalize_rules_payload(rules: CompiledRulesPayload) -> CompiledRulesPayload:
    return {
        event: {
            graph_id: {
                node_id: [dict(handler) for handler in handlers]
                for node_id, handlers in graph_rules.items()
            }
            for graph_id, graph_rules in event_rules.items()
            if graph_rules
        }
        for event, event_rules in rules.items()
        if event_rules
    }


def iter_rules(rules: CompiledRulesPayload) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event, event_rules in rules.items():
        for graph_id, graph_rules in event_rules.items():
            for node_id, handlers in graph_rules.items():
                for handler_index, handler in enumerate(handlers):
                    output.append(
                        {
                            "event": event,
                            "graph_id": graph_id,
                            "node_id": node_id,
                            "handler": handler,
                            "handler_index": handler_index,
                            "path": f"rules.{event}.{graph_id}.{node_id}[{handler_index}]",
                        }
                    )
    return output


def _text(value: object) -> str:
    return str(value or "").strip()


def _error(path: str, field: str, message: str, handler_index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": "config/events.json", "field": field, "message": message}
    if path:
        payload["config_path"] = path
    if handler_index is not None:
        payload["handler_index"] = handler_index
    return payload
