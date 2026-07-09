from __future__ import annotations

import os
import threading
from typing import Any

from src.web_backend.profile_storage import AGENT_PROFILE_DIR, get_profile, profile_category_dir, validate_profile_id

from .event_config_store import load_or_create_event_config, write_event_config
from .event_models import (
    ACTIONS,
    EVENTS,
    PRIORITIES,
    TTLS,
    CompiledReceiver,
    CompiledReceiverGroup,
    CompiledRule,
    EMPTY_REGISTRY,
    RuntimeEventRegistry,
)


class EventConfigError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("runtime event config validation failed")
        self.errors = errors


class RuntimeEventRegistryManager:
    def __init__(self, core: object) -> None:
        self.core = core
        self._active = EMPTY_REGISTRY
        self._lock = threading.Lock()

    def active(self) -> RuntimeEventRegistry:
        return self._active

    def load_startup(self) -> dict[str, Any]:
        config = load_or_create_event_config()
        registry = self.compile(config, strict_sources=False)
        with self._lock:
            self._active = registry
        return {"ok": True, "compiled": self._compiled_counts(registry), "warnings": list(registry.warnings)}

    def apply(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = load_or_create_event_config() if config is None else config
        registry = self.compile(payload, strict_sources=True)
        write_event_config(registry.config)
        with self._lock:
            self._active = registry
        return {
            "ok": True,
            "schema_version": registry.schema_version,
            "compiled": self._compiled_counts(registry),
            "warnings": list(registry.warnings),
        }

    def compile(self, config: dict[str, Any], *, strict_sources: bool) -> RuntimeEventRegistry:
        errors: list[dict[str, Any]] = []
        warnings: list[str] = []
        if not isinstance(config, dict):
            raise EventConfigError([_error("", "config", "config must be an object")])
        schema_version = _int_value(config.get("schema_version"), 1)
        if schema_version != 1:
            errors.append(_error("", "schema_version", "schema_version must be 1"))
        enabled = bool(config.get("enabled", True))
        rules = _compile_rules_payload(config.get("rules", {}), errors, warnings)

        producer_index = _compile_builtin_map(config.get("context_producers"), "context_producers", errors)
        notice_index = _compile_builtin_map(config.get("notice_writers"), "notice_writers", errors)
        receiver_group_index = self._compile_receiver_groups(config.get("receiver_groups"), errors, strict_sources)

        rule_index: dict[tuple[str, str, str], list[CompiledRule]] = {}
        enabled_count_by_source: dict[tuple[str, str], int] = {}
        for index, compiled_raw_rule in enumerate(_iter_rules(rules)):
            raw_rule = compiled_raw_rule["rule"]
            path = str(compiled_raw_rule["path"])
            error_count_before_rule = len(errors)
            if not isinstance(raw_rule, dict):
                errors.append(_error(path, "", "rule must be an object", index))
                continue
            if raw_rule.get("enabled", True) is False:
                continue
            source_graph = str(compiled_raw_rule["graph_id"])
            source_node = str(compiled_raw_rule["node_id"])
            if not source_graph:
                errors.append(_error(path, "graph_id", "source graph_id is required", index))
            if not source_node:
                errors.append(_error(path, "node_id", "source node_id is required", index))
            event = str(compiled_raw_rule["event"])
            action = _text(raw_rule.get("action"))
            target = _text(raw_rule.get("target"))
            if event not in EVENTS:
                errors.append(_error(path, "event", f"unsupported event: {event}", index))
            if action not in ACTIONS:
                errors.append(_error(path, "action", f"unsupported action: {action}", index))
            if not target:
                errors.append(_error(path, "target", "target is required", index))
            if strict_sources and source_graph and source_node and not self._node_exists(source_graph, source_node):
                errors.append(_error(path, "node_id", "source node not found", index))
            if action == "context.produce" and target and target not in producer_index:
                errors.append(_error(path, "target", f"unknown context producer: {target}", index))
            if action == "notice.write" and target and target not in notice_index:
                errors.append(_error(path, "target", f"unknown notice writer: {target}", index))
            if action == "node.dispatch" and target and target not in receiver_group_index:
                errors.append(_error(path, "target", f"unknown receiver group: {target}", index))
            if action == "node.dispatch" and target in receiver_group_index and event in EVENTS:
                group = receiver_group_index[target]
                if event not in group.event_profiles:
                    errors.append(
                        _error(
                            path,
                            "event",
                            f"receiver group {target} has no profile for event {event}",
                            index,
                        )
                    )
            params = raw_rule.get("params")
            if params is None:
                params = {}
            if not isinstance(params, dict):
                errors.append(_error(path, "params", "params must be an object", index))
                params = {}
            compiled_params = _compile_params(params, errors, path, index)
            if len(errors) > error_count_before_rule:
                continue
            key = (source_graph, source_node, event)
            enabled_count_by_source[(source_graph, source_node)] = enabled_count_by_source.get((source_graph, source_node), 0) + 1
            if enabled_count_by_source[(source_graph, source_node)] > 50:
                errors.append(_error(path, "source", "source node has more than 50 enabled rules", index))
                continue
            rule_index.setdefault(key, []).append(
                CompiledRule(
                    graph_id=source_graph,
                    node_id=source_node,
                    rule_index=index,
                    event=event,
                    action=action,
                    target=target,
                    params=compiled_params,
                )
            )

        if errors:
            raise EventConfigError(errors)
        frozen_rules = {key: tuple(value) for key, value in rule_index.items()}
        canonical_config = dict(config)
        canonical_config["rules"] = rules
        return RuntimeEventRegistry(
            enabled=enabled,
            schema_version=schema_version,
            rule_index=frozen_rules,
            producer_index=producer_index,
            notice_index=notice_index,
            receiver_group_index=receiver_group_index,
            config=canonical_config,
            warnings=tuple(warnings),
        )

    def _compile_receiver_groups(
        self,
        raw: object,
        errors: list[dict[str, Any]],
        strict_sources: bool,
    ) -> dict[str, CompiledReceiverGroup]:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            errors.append(_error("", "receiver_groups", "receiver_groups must be an object"))
            return {}
        output: dict[str, CompiledReceiverGroup] = {}
        for group_id_raw, group_raw in raw.items():
            error_count_before_group = len(errors)
            group_id = _text(group_id_raw)
            if not group_id:
                errors.append(_error("receiver_groups", "", "receiver group id is required"))
                continue
            if not isinstance(group_raw, dict):
                errors.append(_error(f"receiver_groups.{group_id}", "", "receiver group must be an object"))
                continue
            if group_raw.get("enabled", True) is False:
                continue
            graph_id = _text(group_raw.get("graph_id")) or "Companion"
            if strict_sources and not self._graph_exists(graph_id):
                errors.append(_error(f"receiver_groups.{group_id}", "graph_id", "receiver graph not found"))
            merge_target_raw = group_raw.get("merge_target")
            if not isinstance(merge_target_raw, dict):
                errors.append(_error(f"receiver_groups.{group_id}", "merge_target", "merge_target is required"))
                continue
            merge_target = CompiledReceiver(_text(merge_target_raw.get("graph_id")), _text(merge_target_raw.get("node_id")))
            if not merge_target.graph_id or not merge_target.node_id:
                errors.append(_error(f"receiver_groups.{group_id}.merge_target", "", "merge_target graph_id/node_id are required"))
            elif strict_sources and not self._node_exists(merge_target.graph_id, merge_target.node_id):
                errors.append(_error(f"receiver_groups.{group_id}.merge_target", "node_id", "merge target not found"))

            profiles_raw = group_raw.get("event_profiles")
            event_profiles: dict[str, str] = {}
            if not isinstance(profiles_raw, dict):
                errors.append(_error(f"receiver_groups.{group_id}", "event_profiles", "event_profiles is required"))
            else:
                for event_raw, profile_raw in profiles_raw.items():
                    event = _text(event_raw)
                    profile_id = _text(profile_raw)
                    if event not in EVENTS:
                        errors.append(_error(f"receiver_groups.{group_id}.event_profiles", event, f"unsupported event: {event}"))
                        continue
                    try:
                        safe_profile_id = validate_profile_id(profile_id)
                    except Exception as exc:
                        errors.append(_error(f"receiver_groups.{group_id}.event_profiles", event, str(exc)))
                        continue
                    if strict_sources and get_profile(profile_category_dir(AGENT_PROFILE_DIR), safe_profile_id) is None:
                        errors.append(_error(f"receiver_groups.{group_id}.event_profiles", event, f"agent profile not found: {safe_profile_id}"))
                    event_profiles[event] = safe_profile_id

            receivers: list[CompiledReceiver] = []
            raw_receivers = group_raw.get("receivers", [])
            if not isinstance(raw_receivers, list):
                errors.append(_error(f"receiver_groups.{group_id}", "receivers", "receivers must be a list"))
                raw_receivers = []
            for index, receiver_raw in enumerate(raw_receivers):
                if not isinstance(receiver_raw, dict):
                    errors.append(_error(f"receiver_groups.{group_id}.receivers[{index}]", "", "receiver must be an object"))
                    continue
                receiver = CompiledReceiver(_text(receiver_raw.get("graph_id")), _text(receiver_raw.get("node_id")))
                if not receiver.graph_id or not receiver.node_id:
                    errors.append(_error(f"receiver_groups.{group_id}.receivers[{index}]", "", "receiver graph_id/node_id are required"))
                    continue
                if strict_sources and not self._node_exists(receiver.graph_id, receiver.node_id):
                    errors.append(_error(f"receiver_groups.{group_id}.receivers[{index}]", "node_id", "receiver node not found"))
                    continue
                receivers.append(receiver)
            if group_id and len(errors) == error_count_before_group:
                output[group_id] = CompiledReceiverGroup(
                    group_id=group_id,
                    graph_id=graph_id,
                    merge_target=merge_target,
                    event_profiles=event_profiles,
                    receivers=tuple(receivers),
                )
        return output

    def _graph_exists(self, graph_id: str) -> bool:
        path = self.core.graph_runtime._graph_dir(graph_id)
        return bool(path and os.path.isdir(path))

    def _node_exists(self, graph_id: str, node_id: str) -> bool:
        path = self.core.graph_runtime._node_config_path(node_id, graph_id)
        return bool(path and os.path.exists(path))

    @staticmethod
    def _compiled_counts(registry: RuntimeEventRegistry) -> dict[str, int]:
        source_keys = {(graph_id, node_id) for graph_id, node_id, _event in registry.rule_index.keys()}
        return {
            "source_graphs": len({graph_id for graph_id, _node_id in source_keys}),
            "source_nodes": len(source_keys),
            "rules": sum(len(items) for items in registry.rule_index.values()),
            "enabled_rules": sum(len(items) for items in registry.rule_index.values()),
            "context_producers": len(registry.producer_index),
            "notice_writers": len(registry.notice_index),
            "receiver_groups": len(registry.receiver_group_index),
        }


def _compile_rules_payload(raw: object, errors: list[dict[str, Any]], warnings: list[str]) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
    if raw is None:
        raw = {}
    if isinstance(raw, list):
        output: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        seen: set[tuple[str, str, str]] = set()
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
            key = (event, graph_id, node_id)
            if key in seen:
                warnings.append(f"duplicate legacy rule collapsed for {event}/{graph_id}/{node_id}; last rule wins")
            seen.add(key)
            output.setdefault(event, {}).setdefault(graph_id, {})[node_id] = _rule_without_keys(item)
        return output
    if not isinstance(raw, dict):
        errors.append(_error("", "rules", "rules must be an object keyed by event"))
        return {}

    output: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for event_raw, graph_rules_raw in raw.items():
        event = _text(event_raw)
        if event not in EVENTS:
            errors.append(_error("rules", event, f"unsupported event: {event}"))
            continue
        if not isinstance(graph_rules_raw, dict):
            errors.append(_error(f"rules.{event}", "", "event rules must be an object keyed by graph id"))
            continue
        event_rules: dict[str, dict[str, dict[str, Any]]] = {}
        for graph_raw, node_rules_raw in graph_rules_raw.items():
            graph_id = _text(graph_raw)
            if not graph_id:
                errors.append(_error(f"rules.{event}", "graph_id", "graph id is required"))
                continue
            if not isinstance(node_rules_raw, dict):
                errors.append(_error(f"rules.{event}.{graph_id}", "", "graph rules must be an object keyed by node id"))
                continue
            graph_rules: dict[str, dict[str, Any]] = {}
            for node_raw, rule_raw in node_rules_raw.items():
                node_id = _text(node_raw)
                if not node_id:
                    errors.append(_error(f"rules.{event}.{graph_id}", "node_id", "node id is required"))
                    continue
                if not isinstance(rule_raw, dict):
                    errors.append(_error(f"rules.{event}.{graph_id}.{node_id}", "", "rule must be an object"))
                    continue
                graph_rules[node_id] = _rule_without_keys(rule_raw)
            if graph_rules:
                event_rules[graph_id] = graph_rules
        if event_rules:
            output[event] = event_rules
    return output


def _iter_rules(rules: dict[str, dict[str, dict[str, dict[str, Any]]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event, event_rules in rules.items():
        for graph_id, graph_rules in event_rules.items():
            for node_id, rule in graph_rules.items():
                output.append(
                    {
                        "event": event,
                        "graph_id": graph_id,
                        "node_id": node_id,
                        "rule": rule,
                        "path": f"rules.{event}.{graph_id}.{node_id}",
                    }
                )
    return output


def _rule_without_keys(raw: dict[str, Any]) -> dict[str, Any]:
    output = dict(raw)
    output.pop("source", None)
    output.pop("event", None)
    return output


def _compile_builtin_map(raw: object, field: str, errors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append(_error("", field, f"{field} must be an object"))
        return {}
    output: dict[str, dict[str, Any]] = {}
    for item_id_raw, item_raw in raw.items():
        item_id = _text(item_id_raw)
        if not item_id or not isinstance(item_raw, dict):
            errors.append(_error(field, item_id, f"{field} entry must be an object"))
            continue
        if item_raw.get("enabled", True) is False:
            continue
        if _text(item_raw.get("kind")) != "builtin":
            errors.append(_error(field, item_id, f"{field} entry kind must be builtin"))
            continue
        priority = _text(item_raw.get("priority")) or "normal"
        if priority not in PRIORITIES:
            errors.append(_error(field, item_id, "priority must be low, normal, or high"))
            continue
        output[item_id] = dict(item_raw)
    return output


def _compile_params(raw: dict[str, Any], errors: list[dict[str, Any]], path: str, rule_index: int) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if "ttl" in raw:
        ttl = _text(raw.get("ttl"))
        if ttl not in TTLS:
            errors.append(_error(path, "ttl", "ttl must be current_run, next_turn, or persistent", rule_index))
        else:
            output["ttl"] = ttl
    if "priority" in raw:
        priority = _text(raw.get("priority"))
        if priority not in PRIORITIES:
            errors.append(_error(path, "priority", "priority must be low, normal, or high", rule_index))
        else:
            output["priority"] = priority
    if "max_chars" in raw:
        try:
            max_chars = int(raw.get("max_chars") or 0)
        except Exception:
            max_chars = 0
        if max_chars <= 0:
            errors.append(_error(path, "max_chars", "max_chars must be positive", rule_index))
        else:
            output["max_chars"] = min(max_chars, 64000)
    return output


def _text(value: object) -> str:
    return str(value or "").strip()


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _error(path: str, field: str, message: str, rule_index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": "config/events.json", "field": field, "message": message}
    if path:
        payload["config_path"] = path
    if rule_index is not None:
        payload["rule_index"] = rule_index
    return payload
