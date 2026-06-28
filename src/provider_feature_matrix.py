from __future__ import annotations

from typing import Any


PROVIDER_FEATURE_SCHEMA_VERSION = 1


def build_provider_feature_matrix(provider_config: dict[str, Any] | None) -> dict[str, Any]:
    config = provider_config if isinstance(provider_config, dict) else {}
    provider_type = str(config.get("type") or "").strip().lower()
    if provider_type == "openai":
        responses_api = config.get("responsesApi") is True
        return _payload(
            responses_api={
                "supported": responses_api,
                "values": ["enabled", "disabled"],
                "requires": "responsesApi=true",
                "transport": "responses",
            },
            web_search={
                "supported": responses_api,
                "values": ["enabled", "disabled"],
                "requires": "responsesApi=true",
                "transport": "responses" if responses_api else "",
            },
            thinking={"supported": False, "values": []},
            reasoning_effort={"supported": True, "values": ["minimal", "low", "medium", "high", "xhigh"]},
        )
    if provider_type == "doubao":
        responses_api = config.get("responsesApi") is True
        return _payload(
            responses_api={
                "supported": responses_api,
                "values": ["enabled", "disabled"],
                "requires": "responsesApi=true",
                "transport": "responses" if responses_api else "",
            },
            web_search={
                "supported": responses_api,
                "values": ["enabled", "disabled"],
                "requires": "responsesApi=true",
                "transport": "responses" if responses_api else "",
            },
            thinking={"supported": True, "values": ["enabled", "disabled", "auto"]},
            reasoning_effort={"supported": False, "values": []},
        )
    if provider_type == "zhipu":
        return _payload(
            responses_api={"supported": False, "values": []},
            web_search={"supported": False, "values": []},
            thinking={"supported": True, "values": ["enabled", "disabled"]},
            reasoning_effort={"supported": True, "values": ["minimal", "low", "medium", "high", "xhigh"]},
        )
    if provider_type == "gemini":
        return _payload(
            responses_api={"supported": False, "values": []},
            web_search={"supported": False, "values": []},
            thinking={"supported": False, "values": []},
            reasoning_effort={"supported": False, "values": []},
        )
    return _payload(
        responses_api={"supported": False, "values": []},
        web_search={"supported": False, "values": []},
        thinking={"supported": False, "values": []},
        reasoning_effort={"supported": False, "values": []},
    )


def _payload(**features: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_FEATURE_SCHEMA_VERSION,
        **{name: _feature(value) for name, value in features.items()},
    }


def _feature(value: dict[str, Any]) -> dict[str, Any]:
    supported = bool(value.get("supported"))
    values = value.get("values")
    out: dict[str, Any] = {
        "supported": supported,
        "values": [str(item) for item in values if str(item or "").strip()] if isinstance(values, list) else [],
    }
    requires = str(value.get("requires") or "").strip()
    if requires:
        out["requires"] = requires
    transport = str(value.get("transport") or "").strip()
    if transport:
        out["transport"] = transport
    return out

