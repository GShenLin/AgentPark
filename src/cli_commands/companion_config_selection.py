from __future__ import annotations

from typing import Any

from src.config_loader import ConfigLoader
from src.capabilities.registry import CapabilityRegistry, FIELD_BY_KIND
from src.provider_options import build_provider_options_for_support_modes
from src.web_backend.node_config_service import node_config_service


REASONING_EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "auto")


def provider_choices(mode: str) -> list[tuple[str, str]]:
    options = build_provider_options_for_support_modes([str(mode or "chat").strip() or "chat"])
    return [(str(item["value"]), str(item["label"])) for item in options]


def reasoning_choices(provider_id: str) -> list[tuple[str, str]]:
    provider = _require_provider(provider_id)
    return [(value, value) for value in _provider_reasoning_values(provider)]


def update_companion_provider(target: Any, provider_id: str) -> str | None:
    safe_provider_id = str(provider_id or "").strip()
    provider = _require_provider(safe_provider_id)
    supported_efforts = _provider_reasoning_values(provider)
    current_effort = str(target.config.get("reasoning_effort") or "").strip()
    next_effort = _resolve_reasoning_effort(current_effort, provider, supported_efforts)

    def mutate(config: dict[str, Any]) -> None:
        config["provider_id"] = safe_provider_id
        if next_effort is None:
            config.pop("reasoning_effort", None)
        else:
            config["reasoning_effort"] = next_effort

    node_config_service.update(str(target.config_path), mutate)
    target.config["provider_id"] = safe_provider_id
    if next_effort is None:
        target.config.pop("reasoning_effort", None)
    else:
        target.config["reasoning_effort"] = next_effort
    return next_effort


def update_companion_config(target: Any, field: str, value: str) -> None:
    safe_field = str(field or "").strip()
    if safe_field not in {"provider_id", "reasoning_effort"}:
        raise ValueError(f"unsupported Companion config field: {safe_field}")
    safe_value = str(value or "").strip()
    if not safe_value:
        raise ValueError(f"{safe_field} is required")

    def mutate(config: dict[str, Any]) -> None:
        config[safe_field] = safe_value

    node_config_service.update(str(target.config_path), mutate)
    target.config[safe_field] = safe_value


def capability_choices(target: Any, kind: str) -> tuple[list[tuple[str, str]], set[str]]:
    safe_kind = str(kind or "").strip()
    if safe_kind not in {"tool", "mcp", "skill"}:
        raise ValueError(f"unsupported capability kind: {safe_kind}")
    payload = CapabilityRegistry().discover_payload(target.config).get(safe_kind)
    if not isinstance(payload, dict):
        return [], set()
    choices: list[tuple[str, str]] = []
    for item in payload.get("available") or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        label = str(item.get("label") or value).strip() or value
        choices.append((value, label))
    selected = {str(value).strip() for value in payload.get("selected") or [] if str(value).strip()}
    return choices, selected


def toggle_companion_capability(target: Any, kind: str, capability_id: str) -> bool:
    safe_kind = str(kind or "").strip()
    if safe_kind not in {"tool", "mcp", "skill"}:
        raise ValueError(f"unsupported capability kind: {safe_kind}")
    safe_id = str(capability_id or "").strip()
    if not safe_id:
        raise ValueError("capability id is required")
    field = FIELD_BY_KIND[safe_kind]
    current = _string_list(target.config.get(field), field)
    enabled = safe_id in current
    if not enabled:
        CapabilityRegistry().validate_requested(safe_kind, [safe_id], target.config)

    def mutate(config: dict[str, Any]) -> None:
        selected = _string_list(config.get(field), field)
        if enabled:
            config[field] = [value for value in selected if value != safe_id]
        elif safe_id not in selected:
            config[field] = [*selected, safe_id]

    node_config_service.update(str(target.config_path), mutate)
    if enabled:
        target.config[field] = [value for value in current if value != safe_id]
    else:
        target.config[field] = [*current, safe_id]
    return not enabled


def _require_provider(provider_id: str) -> dict[str, Any]:
    safe_provider_id = str(provider_id or "").strip()
    providers = ConfigLoader().get_all_providers()
    provider = providers.get(safe_provider_id) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise ValueError(f"provider is not configured: {safe_provider_id}")
    return provider


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Companion config field {field} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Companion config field {field} must contain non-empty strings")
        text = item.strip()
        if text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _provider_reasoning_values(provider: dict[str, Any]) -> list[str]:
    reasoning = (provider.get("features") or {}).get("reasoning_effort")
    if not isinstance(reasoning, dict) or reasoning.get("supported") is not True:
        return []
    values = reasoning.get("values")
    if not isinstance(values, list):
        return []
    return [text for value in values if (text := str(value or "").strip())]


def _resolve_reasoning_effort(
    current_effort: str,
    provider: dict[str, Any],
    supported_efforts: list[str],
) -> str | None:
    if not supported_efforts:
        return None
    if current_effort in supported_efforts:
        return current_effort
    configured_default = str(provider.get("reasoningEffort") or "").strip()
    if configured_default in supported_efforts:
        return configured_default
    if current_effort in REASONING_EFFORT_ORDER:
        current_index = REASONING_EFFORT_ORDER.index(current_effort)
        ordered_supported = [value for value in supported_efforts if value in REASONING_EFFORT_ORDER]
        if ordered_supported:
            return min(
                ordered_supported,
                key=lambda value: (abs(REASONING_EFFORT_ORDER.index(value) - current_index), REASONING_EFFORT_ORDER.index(value)),
            )
    return supported_efforts[0]


__all__ = [
    "provider_choices",
    "capability_choices",
    "reasoning_choices",
    "toggle_companion_capability",
    "update_companion_config",
    "update_companion_provider",
]
