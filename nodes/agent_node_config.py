from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from src.web_backend.node_config_service import read_node_config_optional


class AgentNodeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentNodeRunRequest:
    context: dict[str, Any]
    agent_id: str
    graph_id: str
    config_path: str
    config_data: dict[str, Any] | None
    provider_id: str
    instruction: object
    system_prompt: object
    mode: str
    collaboration_mode: str
    web_search: object
    thinking: object
    reasoning_effort: object
    reasoning_summary: object
    public_base_url: object
    working_path: str

    def setting(self, name: str, default: object = None) -> object:
        if self.config_data is not None and name in self.config_data:
            return self.config_data.get(name, default)
        return self.context.get(name, default)


def load_agent_node_run_request(
    context: dict[str, Any] | None,
    *,
    config_path: str,
) -> AgentNodeRunRequest:
    ctx = dict(context or {})
    agent_id = str(ctx.get("node_instance_id") or "").strip() or "agent"
    graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
    config_data = _read_config_data(config_path)

    def setting(name: str, default: object = None) -> object:
        if config_data is not None and name in config_data:
            return config_data.get(name, default)
        return ctx.get(name, default)

    provider_id = str(setting("provider_id", "") or "").strip()
    if not provider_id:
        raise AgentNodeConfigError("provider_id is required")

    return AgentNodeRunRequest(
        context=ctx,
        agent_id=agent_id,
        graph_id=graph_id,
        config_path=config_path,
        config_data=config_data,
        provider_id=provider_id,
        instruction=setting("instruction"),
        system_prompt=setting("system_prompt"),
        mode=str(setting("mode", "chat") or "chat").strip() or "chat",
        collaboration_mode=str(setting("collaboration_mode", "default") or "default").strip() or "default",
        web_search=setting("web_search"),
        thinking=setting("thinking"),
        reasoning_effort=setting("reasoning_effort"),
        reasoning_summary=setting("reasoning_summary"),
        public_base_url=setting("public_base_url"),
        working_path=str(setting("working_path", "") or "").strip(),
    )


def _read_config_data(config_path: str) -> dict[str, Any] | None:
    if not config_path or not os.path.exists(config_path):
        return None
    try:
        data = read_node_config_optional(config_path)
    except Exception as exc:
        raise AgentNodeConfigError(f"failed to read agent config: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentNodeConfigError("agent config must be a JSON object")
    return data
