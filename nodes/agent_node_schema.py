from __future__ import annotations

from src.capabilities.registry import CapabilityRegistry
from src.audio_speaker_catalog import AudioSpeakerCatalog
from src.config_loader import ConfigLoader
from nodes.agent_node_modes import MODE_ORDER, capability_mode, modes_for_field
from nodes.agent_image_generation_schema import materialize_image_generation_schema


def build_agent_config_schema(base_schema: dict, context: dict | None) -> dict:
    schema = dict(base_schema)
    ctx = context if isinstance(context, dict) else {}
    provider_id = str(ctx.get("provider_id") or "").strip()
    provider_config = dict(ConfigLoader().get_all_providers().get(provider_id, {}) or {}) if provider_id else {}
    provider_features = dict(provider_config.get("features") or {})
    configured_modes = provider_config.get("supportmode")
    provider_modes = (
        [str(mode).strip() for mode in configured_modes if str(mode).strip() in MODE_ORDER]
        if isinstance(configured_modes, list)
        else []
    )
    schema = materialize_image_generation_schema(schema, provider_config)
    capability_payload = (
        CapabilityRegistry().discover_payload(context)
        if any(capability_mode(mode) for mode in provider_modes)
        else {}
    )
    for kind, field in (
        ("tool", "tools"),
        ("mcp", "mcp_servers"),
        ("skill", "skills"),
        ("plugin", "plugins"),
    ):
        field_schema = dict(schema.get(field) or {})
        field_schema["type"] = "multiselect"
        field_schema["options"] = list((capability_payload.get(kind) or {}).get("available") or [])
        schema[field] = field_schema

    for key, raw_field in tuple(schema.items()):
        field_schema = dict(raw_field or {})
        field_modes = modes_for_field(key)
        if field_modes:
            field_schema["modes"] = list(field_modes)
        schema[key] = field_schema

    schema.pop("mode", None)
    schema = {
        key: field_schema
        for key, field_schema in schema.items()
        if not field_schema.get("modes")
        or "*" in field_schema.get("modes", [])
        or any(mode in provider_modes for mode in field_schema.get("modes", []))
    }

    speaker_options = AudioSpeakerCatalog().get_provider_options(provider_id) if provider_id else []
    if speaker_options:
        for field in ("audio_speaker", "tts_speaker", "realtime_speaker", "simultrans_speaker"):
            if field in schema:
                field_schema = dict(schema[field] or {})
                existing = field_schema.get("options") if isinstance(field_schema.get("options"), list) else []
                known = {str(item.get("value") or "") for item in existing if isinstance(item, dict)}
                field_schema["options"] = [*existing, *(item for item in speaker_options if item["value"] not in known)]
                schema[field] = field_schema

    for field in ("web_search", "thinking", "reasoning_effort", "reasoning_summary", "tools"):
        if field not in schema:
            continue
        field_schema = dict(schema.get(field) or {})
        feature = provider_features.get(field) if isinstance(provider_features, dict) else None
        if isinstance(feature, dict):
            field_schema["provider_feature"] = dict(feature)
            field_schema["description"] = provider_feature_description(field, feature)
        schema[field] = field_schema

    terminal_keys = ("tools", "mcp_servers", "skills", "plugins")
    ordered_schema = {
        key: value
        for key, value in schema.items()
        if key not in terminal_keys
    }
    for key in terminal_keys:
        if key in schema:
            ordered_schema[key] = schema[key]
    return ordered_schema


def provider_feature_description(field: str, feature: dict) -> str:
    supported = bool(feature.get("supported"))
    values = feature.get("values")
    allowed = (
        ", ".join(str(item) for item in values if str(item or "").strip())
        if isinstance(values, list)
        else ""
    )
    requires = str(feature.get("requires") or "").strip()
    if supported:
        suffix = f" Supported values: {allowed}." if allowed else ""
        return f"{field} is supported by the selected provider.{suffix}"
    if requires:
        return f"{field} is not available for this provider until {requires}."
    return f"{field} is not supported by the selected provider."
