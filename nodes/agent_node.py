import os
import time
from typing import Callable

from nodes.agent_assistant_memory import persist_assistant_tool_call_note
from nodes.agent_message_adapter import (
    append_channel_meta,
    build_agent_output_message,
    build_agent_user_content,
    extract_channel_meta,
    history_envelope_to_agent_message,
)
from nodes.agent_node_config import load_agent_node_run_request
from nodes.agent_stream_runtime import AgentStreamRuntime
from nodes.agent_support.capability_setup import resolve_agent_capabilities
from nodes.agent_mcp_loader import (
    inject_mcp_server_context,
    register_mcp_server_tools,
    with_mcp_caller_context,
)
from nodes.agent_plugin_loader import resolve_plugin_capabilities
from nodes.agent_plugin_tool_loader import register_plugin_tool_definitions
from nodes.agent_skill_loader import (
    load_node_skills,
)
from nodes.agent_skill_scripts import register_skill_script_tools
from nodes.agent_tool_loader import load_configured_tools
from nodes.agent_node_settings import resolve_agent_node_settings
from nodes.base_node import BaseNode
from src.capabilities.registry import CapabilityRegistry
from src.config_loader import ConfigLoader
from src.media_resource_utils import resolve_public_base_url
from src.message_protocol import envelope_text, normalize_envelope
from src.operational_memory import build_operational_memory_summary
from src.providers import create_agent
from src.providers.agent_codex_base_instructions import resolve_agent_codex_base_instructions
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.runtime_cancellation import raise_if_cancel_requested
from src.switch_utils import parse_switch_mode
from src.workspace_settings import get_workspace_root
from src.web_backend.node_memory_store import load_recent_node_memory_records
from src.web_backend.node_goal_runtime import node_goal_context


class Node(BaseNode):
    name = "Agent"
    description = "Agent 节点"
    input_capabilities = [
        "text",
        "resource:image",
        "resource:video",
        "resource:audio",
        "resource:doc",
        "resource:file",
        "resource:url",
        "structured",
        "meta",
    ]
    output_capabilities = [
        "text",
        "resource:image",
        "resource:video",
        "structured",
        "tool_call",
        "meta",
    ]

    config_defaults = {
        "provider_id": "",
        "system_prompt": "",
        "mode": "chat",
        "collaboration_mode": "default",
        "plugins": [],
        "tools": [],
        "mcp_servers": [],
        "web_search": "disabled",
        "thinking": "disabled",
        "reasoning_effort": "high",
    }
    config_schema = {
        "provider_id": {"type": "text", "label": "provider_id"},
        "system_prompt": {"type": "text", "label": "system_prompt"},
        "mode": {"type": "text", "label": "mode"},
        "collaboration_mode": {
            "type": "select",
            "label": "collaboration_mode",
            "options": [
                {"value": "default", "label": "default"},
                {"value": "plan", "label": "plan"},
            ],
        },
        "plugins": {
            "type": "multiselect",
            "label": "plugins",
            "options": [],
        },
        "tools": {
            "type": "multiselect",
            "label": "tools",
            "options": [],
        },
        "mcp_servers": {
            "type": "multiselect",
            "label": "mcp_servers",
            "options": [],
        },
        "web_search": {"type": "text", "label": "web_search"},
        "thinking": {"type": "text", "label": "thinking"},
        "reasoning_effort": {
            "type": "select",
            "label": "reasoning_effort",
            "options": [
                {"value": "minimal", "label": "minimal"},
                {"value": "low", "label": "low"},
                {"value": "medium", "label": "medium"},
                {"value": "high", "label": "high"},
                {"value": "xhigh", "label": "xhigh"},
            ],
        },
    }

    def get_config_schema(self, context: dict | None = None) -> dict:
        schema = super().get_config_schema(context)
        ctx = context if isinstance(context, dict) else {}
        provider_id = str(ctx.get("provider_id") or "").strip()
        provider_features = {}
        if provider_id:
            try:
                provider_features = dict(ConfigLoader().get_all_providers().get(provider_id, {}).get("features") or {})
            except Exception:
                provider_features = {}
        capability_payload = CapabilityRegistry().discover_payload(context)
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
        for field in ("web_search", "thinking", "reasoning_effort"):
            if field not in schema:
                continue
            field_schema = dict(schema.get(field) or {})
            feature = provider_features.get(field) if isinstance(provider_features, dict) else None
            if isinstance(feature, dict):
                field_schema["provider_feature"] = dict(feature)
                field_schema["description"] = self._provider_feature_description(field, feature)
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
        schema = ordered_schema
        return schema

    @staticmethod
    def _provider_feature_description(field: str, feature: dict) -> str:
        supported = bool(feature.get("supported"))
        values = feature.get("values")
        allowed = ", ".join(str(item) for item in values if str(item or "").strip()) if isinstance(values, list) else ""
        requires = str(feature.get("requires") or "").strip()
        if supported:
            suffix = f" Supported values: {allowed}." if allowed else ""
            return f"{field} is supported by the selected provider.{suffix}"
        if requires:
            return f"{field} is not available for this provider until {requires}."
        return f"{field} is not supported by the selected provider."

    def _load_node_history_messages(
        self,
        context: dict,
        current_message: object,
        provider_id: str,
        public_base_url: object = "",
    ) -> list[dict]:
        messages_path = self._resolve_messages_path(context)
        memory_path = self._resolve_memory_path(context)
        if not messages_path:
            return []

        current = normalize_envelope(current_message, default_role="user")
        current_id = str(current.get("id") or "").strip()
        history_message_limit = resolve_agent_node_settings(ConfigLoader().get_config()).history_message_limit
        records = load_recent_node_memory_records(
            memory_path,
            messages_path,
            limit=history_message_limit + 1,
        )

        history: list[dict] = []
        for item in records:
            envelope = normalize_envelope(item, default_role="assistant")
            if current_id and str(envelope.get("id") or "").strip() == current_id:
                continue
            message = history_envelope_to_agent_message(envelope, provider_id, public_base_url)
            if message is not None:
                history.append(message)
        return history[-history_message_limit:]

    @staticmethod
    def _resolve_stream_callback(context: dict | None) -> Callable[[dict], None] | None:
        if not isinstance(context, dict):
            return None
        callback = context.get("stream_callback")
        if callable(callback):
            return callback
        return None

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        memory_path_for_config = self._resolve_memory_path(ctx)
        agent_dir = os.path.dirname(memory_path_for_config) if memory_path_for_config else ""
        config_path = os.path.join(agent_dir, "config.json")
        run_request = load_agent_node_run_request(ctx, config_path=config_path)
        capability_plan = resolve_agent_capabilities(
            run_request.setting,
            node_id=run_request.agent_id,
            load_skills=load_node_skills,
            resolve_plugins=resolve_plugin_capabilities,
        )
        mcp_settings = with_mcp_caller_context(
            capability_plan.mcp_settings,
            graph_id=run_request.graph_id,
            node_id=run_request.agent_id,
        )

        input_message = normalize_envelope(message, default_role="user")
        channel_meta_parts = extract_channel_meta(input_message)

        memory_path = self._resolve_memory_path(ctx)
        agent = create_agent(
            run_request.provider_id,
            memory_file_path=memory_path,
            system_prompt=run_request.system_prompt if isinstance(run_request.system_prompt, str) else None,
            internal_memory_enabled=False,
        )
        agent.operational_memory_gate_enabled = True
        cancel_source = ctx.get("cancel_event") or ctx.get("cancel_check")
        if cancel_source is not None:
            agent.cancel_event = cancel_source
            agent.cancel_check = ctx.get("cancel_check") or cancel_source
        persist_tool_call_note = lambda message: persist_assistant_tool_call_note(
            message=message,
            memory_path=memory_path,
            messages_path=self._resolve_messages_path(ctx),
        )
        bind_agent_runtime_context(
            agent,
            AgentRuntimeContext(
                graph_id=run_request.graph_id,
                node_id=run_request.agent_id,
                node_type_id="agent_node",
                workspace_root=get_workspace_root(),
                working_path=run_request.working_path,
                collaboration_mode=run_request.collaboration_mode,
                shell="powershell" if os.name == "nt" else "",
                responses_system_prompt_as_instructions=_uses_openai_responses(agent),
                skill_resource_roots=capability_plan.skill_resource_roots,
                persist_assistant_tool_call_note=persist_tool_call_note,
            ),
        )
        codex_context_role = _codex_like_context_role(agent)
        effective_system_prompt = (
            resolve_agent_codex_base_instructions(agent, explicit_system_prompt=run_request.system_prompt)
            if _uses_openai_responses(agent)
            else str(run_request.system_prompt or "").strip()
        )

        load_configured_tools(agent, capability_plan.tool_names)
        if capability_plan.plugin_capabilities.tool_definitions:
            register_plugin_tool_definitions(agent, capability_plan.plugin_capabilities.tool_definitions)
        skill_definitions = [
            *capability_plan.selected_skill_definitions,
            *capability_plan.plugin_capabilities.skill_definitions,
        ]
        register_skill_script_tools(agent, skill_definitions)
        if capability_plan.mcp_server_names:
            register_mcp_server_tools(
                agent,
                list(capability_plan.mcp_server_names),
                settings=mcp_settings,
            )

        if effective_system_prompt:
            has_system = any((msg or {}).get("role") == "system" for msg in getattr(agent, "messages", []) or [])
            if not has_system:
                agent.Message("system", effective_system_prompt)
        operational_memory_summary = build_operational_memory_summary(
            os.path.join(os.path.dirname(memory_path), "operational_memory.json") if memory_path else ""
        )
        if operational_memory_summary:
            agent.Message(codex_context_role, operational_memory_summary, persist=False)
        if capability_plan.mcp_server_names:
            inject_mcp_server_context(
                agent,
                list(capability_plan.mcp_server_names),
                settings=mcp_settings,
                role=codex_context_role,
            )
        self._inject_configured_skills(
            agent,
            {"skills": list(capability_plan.skill_names)},
            node_id=run_request.agent_id,
            extra_skills=skill_definitions,
            role=codex_context_role,
        )
        goal_context = node_goal_context(run_request.config_data or ctx)
        if goal_context:
            agent.Message("user", goal_context, persist=False)

        resolved_public_base_url = resolve_public_base_url(run_request.public_base_url, run_request.provider_id)
        for history_message in self._load_node_history_messages(ctx, input_message, run_request.provider_id, resolved_public_base_url):
            agent.Message(history_message["role"], history_message["content"], persist=False)

        user_content = build_agent_user_content(run_request.provider_id, run_request.mode, input_message, resolved_public_base_url)
        agent.Message("user", user_content, persist=False)
        web_search_mode = parse_switch_mode(run_request.web_search, default="disabled", allow_auto=False)
        thinking_mode = parse_switch_mode(run_request.thinking, default="disabled", allow_auto=False)
        reasoning_effort = run_request.reasoning_effort
        if reasoning_effort is None:
            reasoning_effort = self.config_defaults["reasoning_effort"]
        stream_runtime = AgentStreamRuntime(self._resolve_stream_callback(ctx))

        start_time = time.monotonic()
        raise_if_cancel_requested(cancel_source)
        response = stream_runtime.send(
            agent,
            {
                "run_tools": True,
                "mode": run_request.mode,
                "web_search": web_search_mode,
                "thinking": thinking_mode,
                "reasoning_effort": reasoning_effort,
                "stream": True,
                "stream_handler": stream_runtime.on_stream_delta,
            },
        )
        min_delay_ms = resolve_agent_node_settings(ConfigLoader().get_config()).min_send_delay_ms
        if min_delay_ms > 0:
            elapsed = time.monotonic() - start_time
            remain = min_delay_ms / 1000 - elapsed
            if remain > 0:
                deadline = time.monotonic() + remain
                while True:
                    raise_if_cancel_requested(cancel_source)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(0.05, remaining))
        raise_if_cancel_requested(cancel_source)
        output_message = build_agent_output_message(response)
        output_message = append_channel_meta(output_message, channel_meta_parts)
        final_text = envelope_text(output_message).strip()
        stream_runtime.emit_done(final_text)
        return {
            "display": envelope_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }


def _codex_like_context_role(agent: object) -> str:
    if _uses_openai_responses(agent):
        return "developer"
    return "system"


def _uses_openai_responses(agent: object) -> bool:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        return False
    provider_type = str(config.get("type") or "").strip().lower()
    return provider_type == "openai" and config.get("responsesApi") is True
