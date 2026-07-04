from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

RUNTIME_CONTEXT_ATTR = "_agentpark_runtime_context"


@dataclass(frozen=True)
class AgentRuntimeContext:
    graph_id: str = ""
    node_id: str = ""
    node_type_id: str = ""
    workspace_root: str = ""
    working_path: str = ""
    graph_working_path: str = ""
    collaboration_mode: str = ""
    shell: str = ""
    sandbox_mode: str = ""
    network_access: str = ""
    approval_policy: str = ""
    responses_system_prompt_as_instructions: bool = False
    skill_resource_roots: Mapping[str, str] = field(default_factory=dict)
    persist_assistant_tool_call_note: Callable[[dict[str, Any]], None] | None = None
    companion_notifier: Callable[[dict[str, Any]], None] | None = None

    def with_defaults(self) -> "AgentRuntimeContext":
        return AgentRuntimeContext(
            graph_id=self.graph_id,
            node_id=self.node_id,
            node_type_id=self.node_type_id,
            workspace_root=self.workspace_root,
            working_path=self.working_path,
            graph_working_path=self.graph_working_path,
            collaboration_mode=self.collaboration_mode,
            shell=self.shell,
            sandbox_mode=self.sandbox_mode,
            network_access=self.network_access,
            approval_policy=self.approval_policy,
            responses_system_prompt_as_instructions=bool(self.responses_system_prompt_as_instructions),
            skill_resource_roots=dict(self.skill_resource_roots or {}),
            persist_assistant_tool_call_note=self.persist_assistant_tool_call_note,
            companion_notifier=self.companion_notifier,
        )


def bind_agent_runtime_context(agent: object, context: AgentRuntimeContext) -> AgentRuntimeContext:
    resolved = context.with_defaults()
    setattr(agent, RUNTIME_CONTEXT_ATTR, resolved)
    _write_legacy_runtime_attributes(agent, resolved)
    return resolved


def get_agent_runtime_context(agent: object = None) -> AgentRuntimeContext:
    existing = getattr(agent, RUNTIME_CONTEXT_ATTR, None)
    if isinstance(existing, AgentRuntimeContext):
        return existing.with_defaults()
    return _context_from_legacy_agent(agent).with_defaults()


def _context_from_legacy_agent(agent: object = None) -> AgentRuntimeContext:
    config = getattr(agent, "config", None)
    cfg = config if isinstance(config, dict) else {}
    return AgentRuntimeContext(
        graph_id=_first_non_empty(getattr(agent, "_aitools_graph_id", None), cfg.get("graph_id")),
        node_id=_first_non_empty(
            getattr(agent, "_aitools_node_id", None),
            cfg.get("node_instance_id"),
            cfg.get("agent_id"),
            cfg.get("node_id"),
        ),
        node_type_id=_first_non_empty(getattr(agent, "_aitools_node_type_id", None), cfg.get("node_type_id")),
        workspace_root=_first_non_empty(getattr(agent, "_aitools_workspace_root", None), cfg.get("workspace_root")),
        working_path=_first_non_empty(getattr(agent, "_aitools_working_path", None), cfg.get("working_path")),
        graph_working_path=_first_non_empty(
            getattr(agent, "_aitools_graph_working_path", None),
            cfg.get("graph_working_path"),
        ),
        collaboration_mode=_first_non_empty(
            getattr(agent, "_aitools_collaboration_mode", None),
            cfg.get("collaborationMode"),
            cfg.get("collaboration_mode"),
        ),
        shell=_first_non_empty(getattr(agent, "_aitools_shell", None), cfg.get("shell")),
        sandbox_mode=_first_non_empty(
            getattr(agent, "_aitools_sandbox_mode", None),
            cfg.get("sandbox_mode"),
            cfg.get("sandboxMode"),
        ),
        network_access=_first_non_empty(
            getattr(agent, "_aitools_network_access", None),
            cfg.get("network_access"),
            cfg.get("networkAccess"),
        ),
        approval_policy=_first_non_empty(
            getattr(agent, "_aitools_approval_policy", None),
            cfg.get("approval_policy"),
            cfg.get("approvalPolicy"),
        ),
        responses_system_prompt_as_instructions=bool(
            getattr(agent, "_aitools_responses_system_prompt_as_instructions", False)
        ),
        skill_resource_roots=_mapping_attr(agent, "_aitools_skill_resource_roots"),
        persist_assistant_tool_call_note=_callable_attr(agent, "_aitools_persist_assistant_tool_call_note"),
        companion_notifier=_callable_attr(agent, "_aitools_companion_notifier"),
    )


def _write_legacy_runtime_attributes(agent: object, context: AgentRuntimeContext) -> None:
    values = {
        "_aitools_graph_id": context.graph_id,
        "_aitools_node_id": context.node_id,
        "_aitools_node_type_id": context.node_type_id,
        "_aitools_workspace_root": context.workspace_root,
        "_aitools_working_path": context.working_path,
        "_aitools_graph_working_path": context.graph_working_path,
        "_aitools_collaboration_mode": context.collaboration_mode,
        "_aitools_shell": context.shell,
        "_aitools_sandbox_mode": context.sandbox_mode,
        "_aitools_network_access": context.network_access,
        "_aitools_approval_policy": context.approval_policy,
        "_aitools_responses_system_prompt_as_instructions": context.responses_system_prompt_as_instructions,
    }
    for name, value in values.items():
        if value not in ("", None):
            setattr(agent, name, value)
    if context.skill_resource_roots:
        setattr(agent, "_aitools_skill_resource_roots", dict(context.skill_resource_roots))
    if context.persist_assistant_tool_call_note is not None:
        setattr(agent, "_aitools_persist_assistant_tool_call_note", context.persist_assistant_tool_call_note)
    if context.companion_notifier is not None:
        setattr(agent, "_aitools_companion_notifier", context.companion_notifier)


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _mapping_attr(agent: object, name: str) -> Mapping[str, str]:
    value = getattr(agent, name, None)
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if str(key or "").strip()}


def _callable_attr(agent: object, name: str) -> Callable[[dict[str, Any]], None] | None:
    value = getattr(agent, name, None)
    return value if callable(value) else None
