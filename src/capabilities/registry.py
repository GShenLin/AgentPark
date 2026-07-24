from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from nodes.agent_mcp_loader import list_available_mcp_server_options
from nodes.agent_plugin_loader import list_available_plugin_options, load_node_plugins
from nodes.agent_skill_loader import list_available_skill_options, load_node_skills
from nodes.agent_tool_loader import list_available_tool_options
from src.mcp.lifecycle import get_mcp_lifecycle_snapshot

from .types import CapabilityDescriptor, CapabilityRef


FIELD_BY_KIND = {
    "tool": "tools",
    "mcp": "mcp_servers",
    "skill": "skills",
    "plugin": "plugins",
}
CAPABILITY_REGISTRY_SCHEMA_VERSION = 1


class CapabilityRegistry:
    def discover(
        self,
        config: dict[str, Any] | None = None,
        *,
        kinds: Iterable[str] | None = None,
    ) -> dict[str, list[CapabilityDescriptor]]:
        node_config = config if isinstance(config, dict) else {}
        requested = set(kinds) if kinds is not None else set(FIELD_BY_KIND.keys())
        selected = {
            kind: set(_validate_selected(node_config.get(field), field))
            for kind, field in FIELD_BY_KIND.items()
        }
        grouped: dict[str, list[CapabilityDescriptor]] = {}
        if "tool" in requested:
            grouped["tool"] = self._options(
                "tool",
                list_available_tool_options(),
                selected["tool"],
                source="workspace",
            )
        if "mcp" in requested:
            grouped["mcp"] = self._mcp_descriptors(selected["mcp"])
        if "skill" in requested:
            grouped["skill"] = self._skill_descriptors(selected["skill"])
        if "plugin" in requested:
            grouped["plugin"] = self._plugin_descriptors(selected["plugin"])
        self._mark_missing_selected(grouped, {k: v for k, v in selected.items() if k in requested})
        return grouped

    def discover_payload(
        self,
        config: dict[str, Any] | None = None,
        *,
        kinds: Iterable[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        grouped = self.discover(config, kinds=kinds)
        payload: dict[str, dict[str, Any]] = {}
        for kind, descriptors in grouped.items():
            field = FIELD_BY_KIND[kind]
            enabled = sorted(item.id for item in descriptors if item.enabled)
            payload[kind] = {
                "schema_version": CAPABILITY_REGISTRY_SCHEMA_VERSION,
                "field": field,
                "selected": enabled,
                "available": [self._option_payload(item) for item in descriptors],
                "descriptors": [item.to_payload() for item in descriptors],
            }
        return payload

    def validate_requested(self, kind: str, names: Iterable[str], config: dict[str, Any] | None = None) -> None:
        descriptors = self.discover(config).get(kind, [])
        available = {item.id for item in descriptors if item.status != "unavailable"}
        missing = [name for name in names if name not in available]
        if missing:
            raise ValueError(f"unknown {kind} name(s): {', '.join(missing)}")

    def _options(
        self,
        kind: str,
        options: Iterable[dict[str, Any]],
        selected: set[str],
        *,
        source: str,
    ) -> list[CapabilityDescriptor]:
        descriptors: list[CapabilityDescriptor] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            value = str(option.get("value") or "").strip()
            if not value:
                continue
            label = str(option.get("label") or value).strip() or value
            version = str(option.get("version") or "").strip()
            descriptors.append(
                CapabilityDescriptor(
                    kind=kind,
                    id=value,
                    label=label,
                    version=version,
                    source=source,
                    enabled=value in selected,
                    status="selected" if value in selected else "available",
                )
            )
        return sorted(descriptors, key=lambda item: (item.label.casefold(), item.id.casefold()))

    def _mcp_descriptors(self, selected: set[str]) -> list[CapabilityDescriptor]:
        descriptors = self._options("mcp", list_available_mcp_server_options(), selected, source="workspace")
        result: list[CapabilityDescriptor] = []
        for descriptor in descriptors:
            snapshot = get_mcp_lifecycle_snapshot(descriptor.id)
            if not snapshot:
                result.append(descriptor)
                continue
            lifecycle_state = str(snapshot.get("state") or "").strip()
            diagnostics = [f"mcp lifecycle: {lifecycle_state}"]
            for item in snapshot.get("diagnostics") or []:
                diagnostics.append(str(item))
            if snapshot.get("tool_count"):
                diagnostics.append(f"tool_count={int(snapshot.get('tool_count') or 0)}")
            status = "error" if lifecycle_state == "failed" else descriptor.status
            result.append(
                CapabilityDescriptor(
                    kind=descriptor.kind,
                    id=descriptor.id,
                    label=descriptor.label,
                    description=descriptor.description,
                    version=descriptor.version,
                    source=descriptor.source,
                    enabled=descriptor.enabled,
                    dependencies=descriptor.dependencies,
                    config_schema=descriptor.config_schema,
                    status=status,
                    diagnostics=tuple(diagnostics),
                )
            )
        return result

    def _skill_descriptors(self, selected: set[str]) -> list[CapabilityDescriptor]:
        by_id = {item.id: item for item in self._options("skill", list_available_skill_options(), selected, source="skill")}
        for name in selected:
            if name not in by_id:
                continue
            try:
                skills = load_node_skills([name])
                dependencies = tuple(
                    CapabilityRef("mcp", dep)
                    for skill in skills
                    for dep in skill.mcp_servers
                    if isinstance(dep, str) and dep.strip()
                )
                current = by_id[name]
                version = next((skill.version for skill in skills if skill.name == name and skill.version), current.version)
                by_id[name] = CapabilityDescriptor(
                    kind=current.kind,
                    id=current.id,
                    label=current.label,
                    description=current.description,
                    version=version,
                    source=current.source,
                    enabled=True,
                    dependencies=_dedupe_refs(dependencies),
                    status="selected",
                )
            except Exception as exc:
                current = by_id[name]
                by_id[name] = CapabilityDescriptor(
                    kind=current.kind,
                    id=current.id,
                    label=current.label,
                    version=current.version,
                    source=current.source,
                    enabled=True,
                    status="error",
                    diagnostics=(f"{type(exc).__name__}: {exc}",),
                )
        return sorted(by_id.values(), key=lambda item: (item.label.casefold(), item.id.casefold()))

    def _plugin_descriptors(self, selected: set[str]) -> list[CapabilityDescriptor]:
        by_id = {item.id: item for item in self._options("plugin", list_available_plugin_options(), selected, source="plugin")}
        for name in selected:
            if name not in by_id:
                continue
            try:
                plugins = load_node_plugins([name])
                dependencies: list[CapabilityRef] = []
                config_schema: dict[str, Any] = {}
                version = ""
                for plugin in plugins:
                    if plugin.version and not version:
                        version = plugin.version
                    dependencies.extend(CapabilityRef("tool", item) for item in plugin.tools)
                    dependencies.extend(CapabilityRef("tool", item.name) for item in plugin.tool_definitions)
                    dependencies.extend(CapabilityRef("skill", item) for item in plugin.skills)
                    dependencies.extend(CapabilityRef("skill", item.name) for item in plugin.skill_definitions)
                    dependencies.extend(CapabilityRef("mcp", item) for item in plugin.mcp_servers)
                    config_schema.update(dict(plugin.config_schema or {}))
                current = by_id[name]
                by_id[name] = CapabilityDescriptor(
                    kind=current.kind,
                    id=current.id,
                    label=current.label,
                    description=current.description,
                    version=version or current.version,
                    source=current.source,
                    enabled=True,
                    dependencies=_dedupe_refs(dependencies),
                    config_schema=config_schema,
                    status="selected",
                )
            except Exception as exc:
                current = by_id[name]
                by_id[name] = CapabilityDescriptor(
                    kind=current.kind,
                    id=current.id,
                    label=current.label,
                    version=current.version,
                    source=current.source,
                    enabled=True,
                    status="error",
                    diagnostics=(f"{type(exc).__name__}: {exc}",),
                )
        return sorted(by_id.values(), key=lambda item: (item.label.casefold(), item.id.casefold()))

    def _mark_missing_selected(
        self,
        grouped: dict[str, list[CapabilityDescriptor]],
        selected: dict[str, set[str]],
    ) -> None:
        for kind, names in selected.items():
            known = {item.id for item in grouped.get(kind, [])}
            missing = sorted(name for name in names if name not in known)
            grouped.setdefault(kind, []).extend(
                CapabilityDescriptor(
                    kind=kind,
                    id=name,
                    label=name,
                    enabled=True,
                    status="unavailable",
                    diagnostics=(f"selected {kind} is not available: {name}",),
                )
                for name in missing
            )

    def _option_payload(self, descriptor: CapabilityDescriptor) -> dict[str, Any]:
        payload = {
            "value": descriptor.id,
            "label": descriptor.label,
            "kind": descriptor.kind,
            "description": descriptor.description,
            "version": descriptor.version,
            "enabled": descriptor.enabled,
            "source": descriptor.source,
            "status": descriptor.status,
            "diagnostics": list(descriptor.diagnostics),
            "effective": "next_agent_run",
        }
        if descriptor.dependencies:
            payload["dependencies"] = [item.to_payload() for item in descriptor.dependencies]
        if descriptor.config_schema:
            payload["config_schema"] = descriptor.config_schema
        return payload


def discover_capabilities(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return CapabilityRegistry().discover_payload(config)


def _validate_selected(values: object, field: str) -> list[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        raise ValueError(f"node config field {field} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"node config field {field} must contain only strings")
        text = value.strip()
        if not text:
            raise ValueError(f"node config field {field} must contain only non-empty strings")
        if text in seen:
            raise ValueError(f"node config field {field} contains duplicate value: {text}")
        seen.add(text)
        result.append(text)
    return result


def _dedupe_refs(refs: Iterable[CapabilityRef]) -> tuple[CapabilityRef, ...]:
    result: list[CapabilityRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.kind, ref.id)
        if not ref.id or key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return tuple(result)
