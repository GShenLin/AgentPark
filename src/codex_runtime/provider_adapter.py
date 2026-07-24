from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .contracts import CanonicalRequest
from .contracts import CanonicalResult
from .contracts import CanonicalTool
from .contracts import CodexProtocolError


class ChatProtocolAdapter(Protocol):
    def complete(self, request: CanonicalRequest) -> CanonicalResult:
        ...

    def stream(self, request: CanonicalRequest, *, response_id: str = "") -> Iterable[bytes]:
        ...


def provider_protocol(config: dict[str, Any]) -> str:
    if config.get("responsesApi") is True:
        return "responses"
    provider_type = str(config.get("type") or "").strip().lower()
    if provider_type == "claude":
        return "anthropic"
    if provider_type == "gemini":
        return "gemini"
    if provider_type in {"openai", "deepseek", "kimi", "grok", "zhipu", "doubao"}:
        return "openai_chat"
    raise ValueError(
        f"Provider type {provider_type or '<empty>'!r} has no Codex conversational protocol adapter."
    )


def create_chat_adapter(config: dict[str, Any]) -> ChatProtocolAdapter:
    protocol = provider_protocol(config)
    if protocol == "openai_chat":
        from .openai_chat_adapter import OpenAIChatAdapter

        return OpenAIChatAdapter(config)
    if protocol == "anthropic":
        from .anthropic_adapter import AnthropicMessagesAdapter

        return AnthropicMessagesAdapter(config)
    if protocol == "gemini":
        from .gemini_adapter import GeminiGenerateContentAdapter

        return GeminiGenerateContentAdapter(config)
    raise ValueError(f"Protocol {protocol!r} is not a Chat conversion adapter.")


def flatten_tool_choice(raw: object, tools: tuple[CanonicalTool, ...]) -> object:
    if not isinstance(raw, dict) or str(raw.get("type") or "") not in {"function", "custom"}:
        return raw
    name = str(raw.get("name") or "").strip()
    namespace = str(raw.get("namespace") or "").strip()
    matches = [tool for tool in tools if tool.name == name and tool.namespace == namespace]
    if len(matches) != 1:
        raise CodexProtocolError(
            f"Responses tool_choice does not identify exactly one declared tool: namespace={namespace!r}, name={name!r}."
        )
    return {**raw, "name": matches[0].wire_name}
