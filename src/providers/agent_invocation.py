"""Compile AgentConfig once, then invoke through the selected provider contract."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import inspect
import logging
from types import MappingProxyType
from typing import Mapping

from src.provider_feature_matrix import build_provider_feature_matrix

from .agent_config import AgentConfig, AgentSendContext
from .parameter_mapping import ProviderParameterMapping, PROVIDER_PARAMETER_MAPPINGS


LOG = logging.getLogger(__name__)


def _validate_targets(method, targets, *, label: str) -> None:
    """Reflection checks declared contracts; it never discovers or drops fields."""
    signature = inspect.signature(method)
    try:
        signature.bind(None, **dict.fromkeys(targets))
    except TypeError as exc:
        raise TypeError(f"{label} parameter mapping does not match implementation: {exc}") from exc


@dataclass(frozen=True)
class AgentInvocation:
    provider_id: str
    provider_type: str
    mapping: ProviderParameterMapping
    send_kwargs: Mapping
    excluded_fields: Mapping[str, str]

    def send(self, agent, context: AgentSendContext | None = None):
        if not self.mapping.supports_send:
            raise ValueError(f"Provider {self.provider_id!r} requires explicit media generation methods")
        if context is not None and not isinstance(context, AgentSendContext):
            raise TypeError("send context must be AgentSendContext")
        kwargs = deepcopy(dict(self.send_kwargs))
        for name, value in (context or AgentSendContext()).values().items():
            target = self.mapping.send[name]
            if target is not None:
                kwargs[target] = value
            else:
                LOG.info("Provider %s excludes per-call field %s by contract", self.provider_id, name)
        return agent.Send(**kwargs)


def compile_agent_invocation(provider_id: str, provider_config: dict, config: AgentConfig,
                             provider_class: type, *, mapping: ProviderParameterMapping | None = None) -> AgentInvocation:
    if not isinstance(config, AgentConfig):
        raise TypeError("agent_config must be AgentConfig")
    provider_type = provider_config.get("type")
    mapping = mapping or PROVIDER_PARAMETER_MAPPINGS.get(provider_type)
    if mapping is None:
        raise ValueError(f"Provider {provider_id!r} has no parameter mapping for type {provider_type!r}")
    _validate_targets(provider_class.__init__, mapping.constructor.values(), label=f"{provider_type} constructor")
    if mapping.supports_send:
        _validate_targets(provider_class.Send, (v for v in mapping.send.values() if v is not None),
                          label=f"{provider_type}.Send")
    # Agnes uses the OpenAI inference protocol for chat; its media options have
    # a separate native adapter. Capability rules are shared with Settings.
    feature_config = {**provider_config, "type": "openai" if provider_type == "agnes" else provider_type}
    features = build_provider_feature_matrix(feature_config)
    kwargs, excluded = {}, {}
    for name, value in config.values().items():
        target = mapping.send[name]
        if target is None:
            excluded[name] = f"not part of {provider_type}.Send contract"
        elif (config.mode == "chat"
              and name in {"web_search", "thinking", "reasoning_effort", "reasoning_summary"}
              and not features[name]["supported"]):
            excluded[name] = f"not supported by {provider_type} model/transport"
        else:
            kwargs[target] = value
    if excluded:
        LOG.info("Provider %s AgentConfig exclusions: %s", provider_id, excluded)
    return AgentInvocation(provider_id, provider_type, mapping,
                           MappingProxyType(kwargs), MappingProxyType(excluded))


def send_agent(agent, context: AgentSendContext | None = None):
    invocation = getattr(agent, "_agent_invocation", None)
    if not isinstance(invocation, AgentInvocation):
        raise TypeError("Agent must be created through create_agent before configured sends")
    return invocation.send(agent, context)
