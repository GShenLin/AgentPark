from __future__ import annotations

from typing import Any


OPENAI_TEST_CHANNELS = ("chat_completions", "responses")
PROVIDER_TEST_CHANNELS = ("configured", *OPENAI_TEST_CHANNELS)
OPENAI_COMPATIBLE_PROVIDER_TYPES = frozenset({"openai", "doubao", "deepseek"})
OPENAI_DUAL_CHANNEL_PROVIDER_TYPES = frozenset({"openai", "doubao"})


def normalize_provider_test_channel(value: object) -> str:
    channel = str(value or "configured").strip().lower()
    if channel not in PROVIDER_TEST_CHANNELS:
        allowed = ", ".join(PROVIDER_TEST_CHANNELS)
        raise ValueError(f"test_channel must be one of: {allowed}")
    return channel


def resolve_provider_test_channel(provider_type: str, config: dict[str, Any], requested_channel: str) -> str:
    normalized_type = str(provider_type or "").strip().lower()
    channel = normalize_provider_test_channel(requested_channel)
    if normalized_type == "deepseek":
        if channel == "responses":
            raise ValueError("DeepSeek providers support only the chat_completions test channel")
        return "chat_completions"
    if normalized_type in OPENAI_DUAL_CHANNEL_PROVIDER_TYPES:
        if channel != "configured":
            return channel
        return "responses" if config.get("responsesApi") is True else "chat_completions"
    return {
        "zhipu": "chat_completions",
        "claude": "messages",
        "gemini": "generate_content",
        "hyper3d": "native",
    }.get(normalized_type, "native")


def provider_test_channels(provider_type: str, config: dict[str, Any]) -> tuple[str, ...]:
    normalized_type = str(provider_type or "").strip().lower()
    if normalized_type == "deepseek":
        return ("chat_completions",)
    if normalized_type in OPENAI_DUAL_CHANNEL_PROVIDER_TYPES:
        return OPENAI_TEST_CHANNELS
    return (resolve_provider_test_channel(normalized_type, config, "configured"),)


def openai_compatible_endpoint_url(config: dict[str, Any], channel: str) -> str:
    normalized_channel = normalize_provider_test_channel(channel)
    if normalized_channel == "configured":
        raise ValueError("configured test channel must be resolved before building an endpoint URL")
    base_url = str(config.get("baseUrl") or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)].rstrip("/")
            break
    endpoint = "responses" if normalized_channel == "responses" else "chat/completions"
    return f"{base_url}/{endpoint}"
