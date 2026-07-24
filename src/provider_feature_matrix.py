from __future__ import annotations

from typing import Any

from src.grok_reasoning_effort import grok_reasoning_effort_values
from src.kimi_model_contract import kimi_model_family


PROVIDER_FEATURE_SCHEMA_VERSION = 1


def build_provider_feature_matrix(provider_config: dict[str, Any] | None) -> dict[str, Any]:
    config = provider_config if isinstance(provider_config, dict) else {}
    provider_type = str(config.get("type") or "").strip()
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
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking={
                "supported": not responses_api,
                "values": ["enabled", "disabled", "auto"] if not responses_api else [],
                "requires": "responsesApi=false",
                "transport": "chat_completions" if not responses_api else "",
            },
            reasoning_effort={"supported": True, "values": ["minimal", "low", "medium", "high", "xhigh"]},
            reasoning_summary={
                "supported": responses_api,
                "values": ["auto", "concise", "detailed", "disabled"] if responses_api else [],
                "requires": "responsesApi=true",
                "transport": "responses" if responses_api else "",
            },
        )
    if provider_type == "grok":
        responses_api = config.get("responsesApi") is True
        reasoning_effort_values = grok_reasoning_effort_values(config.get("model"))
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
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking={"supported": False, "values": []},
            reasoning_effort={
                "supported": bool(reasoning_effort_values),
                "values": reasoning_effort_values,
                "transport": "responses" if responses_api else "chat_completions",
            },
            reasoning_summary={"supported": False, "values": []},
        )
    if provider_type == "deepseek":
        return _payload(
            responses_api={"supported": False, "values": []},
            web_search={"supported": False, "values": []},
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking={
                "supported": True,
                "values": ["enabled", "disabled"],
                "transport": "chat_completions",
            },
            reasoning_effort={
                "supported": True,
                "values": ["high", "max"],
                "transport": "chat_completions",
            },
            reasoning_summary={"supported": False, "values": []},
        )
    if provider_type == "kimi":
        family = kimi_model_family(config.get("model"))
        web_search_supported = family in {"k3", "k2.6", "k2.5"}
        if family == "k3":
            thinking = {"supported": False, "values": []}
            reasoning_effort = {"supported": True, "values": ["max"], "transport": "chat_completions"}
        elif family == "k2.7-code":
            thinking = {"supported": True, "values": ["enabled"], "transport": "chat_completions"}
            reasoning_effort = {"supported": False, "values": []}
        elif family in {"k2.6", "k2.5"}:
            thinking = {
                "supported": True,
                "values": ["enabled", "disabled"],
                "transport": "chat_completions",
            }
            reasoning_effort = {"supported": False, "values": []}
        else:
            thinking = {"supported": False, "values": []}
            reasoning_effort = {"supported": False, "values": []}
        return _payload(
            responses_api={"supported": False, "values": []},
            web_search={
                "supported": web_search_supported,
                "values": ["enabled", "disabled"] if web_search_supported else [],
                "transport": "chat_completions" if web_search_supported else "",
            },
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            reasoning_summary={"supported": False, "values": []},
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
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking={
                "supported": responses_api,
                "values": ["enabled", "disabled", "auto"] if responses_api else [],
                "requires": "responsesApi=true",
                "transport": "responses" if responses_api else "",
            },
            reasoning_effort={
                "supported": responses_api,
                "values": ["low", "medium", "high"] if responses_api else [],
                "requires": "responsesApi=true",
                "transport": "responses" if responses_api else "",
            },
            reasoning_summary={"supported": False, "values": []},
        )
    if provider_type == "zhipu":
        return _payload(
            responses_api={"supported": False, "values": []},
            web_search={"supported": False, "values": []},
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking={"supported": True, "values": ["enabled", "disabled"]},
            reasoning_effort={"supported": True, "values": ["minimal", "low", "medium", "high", "xhigh"]},
            reasoning_summary={"supported": False, "values": []},
        )
    if provider_type == "claude":
        return _payload(
            responses_api={"supported": False, "values": []},
            web_search={"supported": True, "values": ["enabled", "disabled"], "transport": "messages"},
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking={"supported": True, "values": ["enabled", "disabled", "auto"], "transport": "messages"},
            reasoning_effort={"supported": True, "values": ["low", "medium", "high", "xhigh", "max"], "transport": "messages"},
            reasoning_summary={"supported": False, "values": []},
        )
    if provider_type == "gemini":
        return _payload(
            responses_api={"supported": False, "values": []},
            web_search={"supported": False, "values": []},
            tools={"supported": True, "values": ["enabled", "disabled"]},
            thinking={"supported": False, "values": []},
            reasoning_effort={"supported": False, "values": []},
            reasoning_summary={"supported": False, "values": []},
        )
    return _payload(
        responses_api={"supported": False, "values": []},
        web_search={"supported": False, "values": []},
        tools={"supported": False, "values": []},
        thinking={"supported": False, "values": []},
        reasoning_effort={"supported": False, "values": []},
        reasoning_summary={"supported": False, "values": []},
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
