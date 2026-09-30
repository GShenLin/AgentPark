"""Translate resolved node settings into the provider-independent configuration."""
from types import SimpleNamespace

from nodes.agent_node_modes import settings_for_mode
from nodes.agent_provider_runtime import stream_enabled
from src.providers.agent_config import AgentConfig
from src.switch_utils import parse_switch_mode


def node_agent_config(request, run_mode: str, provider_config: dict, defaults: dict) -> AgentConfig:
    return AgentConfig(
        run_tools=True, mode=run_mode,
        web_search=parse_switch_mode(request.web_search, default="disabled", allow_auto=False),
        thinking=parse_switch_mode(request.thinking, default="disabled", allow_auto=False),
        reasoning_effort=request.reasoning_effort if request.reasoning_effort is not None
        else defaults["reasoning_effort"],
        reasoning_summary=request.reasoning_summary if request.reasoning_summary is not None
        else defaults["reasoning_summary"],
        mode_options=settings_for_mode(run_mode, request.config_data, request.context),
        stream=stream_enabled(SimpleNamespace(config=provider_config)),
    )
