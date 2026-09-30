"""Explicit Python adapter contracts, not signature-based parameter filtering.

Each source field has a destination or an explicit exclusion. Protocol payload
translation (e.g. reasoning.effort) remains owned by the provider runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Mapping

from .agent_config import AgentConfig, AgentSendContext


CONFIG_FIELDS = frozenset(field.name for field in fields(AgentConfig))
CONTEXT_FIELDS = frozenset(field.name for field in fields(AgentSendContext))
CONSTRUCTOR_FIELDS = frozenset({"provider_id", "memory_file_path", "system_prompt", "internal_memory_enabled"})


@dataclass(frozen=True)
class ProviderParameterMapping:
    constructor: Mapping[str, str]
    send: Mapping[str, str | None]
    supports_send: bool = True

    def __post_init__(self):
        if set(self.constructor) != CONSTRUCTOR_FIELDS:
            raise ValueError("Provider constructor mapping must cover every constructor field")
        if set(self.send) != CONFIG_FIELDS | CONTEXT_FIELDS:
            raise ValueError("Provider send mapping must cover every AgentConfig/AgentSendContext field")
        if any(value is None for value in self.constructor.values()):
            raise ValueError("Provider constructor fields require explicit targets")
        if type(self.supports_send) is not bool:
            raise TypeError("supports_send must be a boolean")
        for mapping in (self.constructor, self.send):
            targets = [value for value in mapping.values() if value is not None]
            if any(not isinstance(value, str) or not value for value in targets):
                raise ValueError("Provider parameter targets must be non-empty strings")
            if len(targets) != len(set(targets)):
                raise ValueError("Provider parameter mapping has duplicate targets")
        object.__setattr__(self, "constructor", MappingProxyType(dict(self.constructor)))
        object.__setattr__(self, "send", MappingProxyType(dict(self.send)))


def _mapping(*excluded: str, supports_send: bool = True) -> ProviderParameterMapping:
    return ProviderParameterMapping(
        {name: name for name in CONSTRUCTOR_FIELDS},
        {name: None if name in excluded else name for name in CONFIG_FIELDS | CONTEXT_FIELDS},
        supports_send,
    )


PROVIDER_PARAMETER_MAPPINGS = {
    "openai": _mapping(),
    "agnes": _mapping(),
    "deepseek": _mapping(),
    "kimi": _mapping("reasoning_summary"),
    "doubao": _mapping("reasoning_summary"),
    "grok": _mapping("reasoning_summary", "mode_options"),
    "claude": _mapping("reasoning_summary", "mode_options"),
    "gemini": _mapping("reasoning_effort", "reasoning_summary", "thinking_stream_handler"),
    "zhipu": _mapping("reasoning_summary", "mode_options", "thinking_stream_handler"),
    "hyper3d": _mapping(*(CONFIG_FIELDS | CONTEXT_FIELDS), supports_send=False),
    "alpha_matting": _mapping(*(CONFIG_FIELDS | CONTEXT_FIELDS), supports_send=False),
}
