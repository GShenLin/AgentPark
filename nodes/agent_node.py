import os
import time
import uuid

from nodes.agent_assistant_memory import persist_assistant_progress
from nodes.agent_node_contract import (
    AGENT_CONFIG_DEFAULTS,
    AGENT_CONFIG_SCHEMA,
    AGENT_INPUT_CAPABILITIES,
    AGENT_OUTPUT_CAPABILITIES,
)
from nodes.agent_assistant_memory import persist_provider_turn_metadata
from nodes.agent_history import load_agent_history_messages
from nodes.agent_skill_activation import bind_deferred_skills, partition_deferred_skills
from nodes.agent_gateway_usage import build_agent_gateway_usage_recorder
from nodes.agent_message_adapter import (
    append_channel_meta,
    build_agent_output_message,
    build_response_metadata_message,
    build_agent_user_content,
    extract_channel_meta,
)
from nodes.agent_node_config import load_agent_node_run_request
from nodes.agent_node_modes import MODE_ORDER, capability_mode, resolve_input_support_mode
from nodes.agent_node_invocation import node_agent_config
from nodes.agent_node_schema import build_agent_config_schema
from nodes.agent_provider_runtime import effective_instruction
from nodes.agent_provider_runtime import merge_structured_response
from nodes.agent_provider_runtime import resolve_instruction_role
from nodes.agent_provider_runtime import stream_callback
from nodes.agent_provider_runtime import uses_responses_api_context
from nodes.agent_stream_runtime import AgentStreamRuntime
from nodes.agent_support.capability_setup import AgentCapabilityPlan, resolve_agent_capabilities
from nodes.agent_mcp_loader import (
    McpServerLoadError,
    inject_mcp_server_context,
    register_mcp_server_tools,
    with_mcp_caller_context,
)
from nodes.agent_mcp_results import report_mcp_load_failure
from nodes.agent_plugin_loader import resolve_plugin_capabilities
from nodes.agent_plugin_tool_loader import register_plugin_tool_definitions
from nodes.agent_skill_loader import (
    load_node_skills,
)
from nodes.agent_skill_scripts import register_skill_script_tools
from nodes.agent_tool_loader import load_configured_tools
from nodes.agent_node_settings import resolve_agent_node_settings
from nodes.base_node import BaseNode
from src.restart_recovery_context import render_restart_recovery_context
from src.agent_groups.agent_tools import bind_group_tools
from src.config_loader import ConfigLoader
from src.conversation_context.settings import ConversationSettings
from src.access_policy import nondeveloper_filtered_tools
from src.media_resource_utils import resolve_public_base_url
from src.message_protocol import envelope_text, normalize_envelope
from src.long_term_memory.service import prepare_node_memory
from src.providers import create_agent
from src.providers.agent_config import AgentSendContext
from src.provider_models import resolve_provider_model
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.providers.provider_request_usage import ProviderRequestTracker
from src.runtime_events.context_injection import runtime_event_context_from_context
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.tool_stats_store import ToolCallStatsRecorder
from src.tool.access_filter import filter_configured_tool_modules
from src.tool.access_filter import filter_registered_agent_tools
from src.tool.access_filter import is_nondeveloper_context
from src.task_direction_store import archive_legacy_task_artifacts
from src.workspace_settings import get_workspace_root
from src.web_backend.node_goal_runtime import node_goal_context
from src.web_backend.state_store import _consume_node_mid_turn_user_inputs


def _workspace_config():
    loader = ConfigLoader()
    workspace_config = getattr(loader, "get_workspace_config", None)
    config = workspace_config() if callable(workspace_config) else loader.get_config()
    return config


def _resolved_agent_node_settings():
    return resolve_agent_node_settings(_workspace_config())


class Node(BaseNode):
    name = "Agent"
    description = "Agent 节点"
    support_modes = MODE_ORDER
    input_capabilities = AGENT_INPUT_CAPABILITIES
    output_capabilities = AGENT_OUTPUT_CAPABILITIES
    config_defaults = AGENT_CONFIG_DEFAULTS
    config_schema = AGENT_CONFIG_SCHEMA

    def get_config_schema(self, context: dict | None = None) -> dict:
        return build_agent_config_schema(super().get_config_schema(context), context)

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        task_id = str(ctx.get("task_id") or "").strip() or f"direct-{uuid.uuid4().hex}"
        memory_path_for_config = self._resolve_memory_path(ctx)
        agent_dir = os.path.dirname(memory_path_for_config) if memory_path_for_config else ""
        if agent_dir:
            archive_legacy_task_artifacts(agent_dir)
        config_path = str(ctx.get("node_config_path") or "").strip()
        if not config_path:
            config_path = os.path.join(agent_dir, "config.json")
        run_request = load_agent_node_run_request(ctx, config_path=config_path)
        input_message = normalize_envelope(message, default_role="user")
        provider_config = ConfigLoader().get_provider_config(run_request.provider_id)
        selected_model_id = resolve_provider_model(
            {**provider_config, "id": run_request.provider_id},
            run_request.model_id,
        )
        run_mode = resolve_input_support_mode(provider_config.get("supportmode"), input_message)
        capability_plan = (
            resolve_agent_capabilities(
                run_request.setting,
                node_id=run_request.agent_id,
                load_skills=load_node_skills,
                resolve_plugins=resolve_plugin_capabilities,
            )
            if capability_mode(run_mode)
            else AgentCapabilityPlan()
        )
        filtered_tool_names = (
            nondeveloper_filtered_tools()
            if is_nondeveloper_context(ctx)
            else ()
        )
        mcp_settings = with_mcp_caller_context(
            capability_plan.mcp_settings,
            graph_id=run_request.graph_id,
            node_id=run_request.agent_id,
        )

        channel_meta_parts = extract_channel_meta(input_message)

        memory_path = self._resolve_memory_path(ctx)
        agent = create_agent(
            run_request.provider_id,
            memory_file_path=memory_path,
            system_prompt=run_request.system_prompt if isinstance(run_request.system_prompt, str) else None,
            internal_memory_enabled=False,
            model_id=selected_model_id,
            agent_config=node_agent_config(run_request, run_mode, provider_config, self.config_defaults),
        )
        resolved_public_base_url = resolve_public_base_url(run_request.public_base_url, run_request.provider_id)
        cancel_source = ctx.get("cancel_event") or ctx.get("cancel_check")
        if cancel_source is not None:
            agent.cancel_event = cancel_source
            agent.cancel_check = ctx.get("cancel_check") or cancel_source
        persist_progress = lambda message: persist_assistant_progress(
            message=message,
            memory_path=memory_path,
            messages_path=self._resolve_messages_path(ctx),
        )
        persist_turn_metadata = lambda message: persist_provider_turn_metadata(
            message=message,
            memory_path=memory_path,
            messages_path=self._resolve_messages_path(ctx),
        )
        provider_config = getattr(agent, "config", None)
        provider_model_id = (
            str(provider_config.get("model") or "").strip()
            if isinstance(provider_config, dict)
            else ""
        )
        record_provider_usage = build_agent_gateway_usage_recorder(
            workspace_root=get_workspace_root(),
            client_ip=str(ctx.get("access_ip") or ""),
            task_id=task_id,
            model_id=provider_model_id,
        )
        provider_request_tracker = ProviderRequestTracker(on_completion=record_provider_usage)
        def consume_mid_turn_user_inputs() -> list[dict]:
            messages: list[dict] = []
            pending_inputs = _consume_node_mid_turn_user_inputs(config_path)
            consume_group = ctx.get("consume_group_followups")
            if callable(consume_group):
                pending_inputs.extend({"payload": envelope} for envelope in consume_group())
            for pending_item in pending_inputs:
                if not isinstance(pending_item, dict):
                    continue
                envelope = normalize_envelope(pending_item.get("payload"), default_role="user")
                content = build_agent_user_content(
                    run_request.provider_id,
                    run_mode,
                    envelope,
                    resolved_public_base_url,
                )
                if content is None:
                    continue
                if isinstance(content, str) and not content.strip():
                    continue
                if isinstance(content, list) and not content:
                    continue
                message = {"role": "user", "content": content}
                agent.Message("user", content, persist=False)
                messages.append(message)
            return messages

        bind_agent_runtime_context(
            agent,
            AgentRuntimeContext(
                task_id=task_id,
                graph_id=run_request.graph_id,
                node_id=run_request.agent_id,
                node_type_id="agent_node",
                node_directory=agent_dir,
                workspace_root=get_workspace_root(),
                working_path=run_request.working_path,
                remote_enabled=run_request.remote_enabled,
                remote_worker_id=run_request.remote_worker_id,
                collaboration_mode=run_request.collaboration_mode,
                client_ip=str(ctx.get("access_ip") or ""),
                shell="powershell" if os.name == "nt" else "",
                responses_instruction=effective_instruction(agent, run_request.instruction)
                if uses_responses_api_context(agent)
                else "",
                skill_resource_roots=capability_plan.skill_resource_roots,
                persist_assistant_progress=persist_progress,
                persist_provider_turn_metadata=persist_turn_metadata,
                consume_mid_turn_user_inputs=consume_mid_turn_user_inputs,
                begin_tool_call_cancellation=ctx.get("begin_tool_call_cancellation")
                if callable(ctx.get("begin_tool_call_cancellation"))
                else None,
                end_tool_call_cancellation=ctx.get("end_tool_call_cancellation")
                if callable(ctx.get("end_tool_call_cancellation"))
                else None,
                provider_request_tracker=provider_request_tracker,
            ),
        )
        instruction_role = resolve_instruction_role(agent)
        effective_system_prompt = str(run_request.system_prompt or "").strip()

        load_configured_tools(
            agent,
            filter_configured_tool_modules(capability_plan.tool_names, filtered_tool_names),
        )
        if capability_plan.plugin_capabilities.tool_definitions:
            register_plugin_tool_definitions(agent, capability_plan.plugin_capabilities.tool_definitions)
        skill_definitions = [
            *capability_plan.selected_skill_definitions,
            *capability_plan.plugin_capabilities.skill_definitions,
        ]
        eager_skill_definitions, deferred_skill_definitions = partition_deferred_skills(skill_definitions)
        register_skill_script_tools(agent, eager_skill_definitions)
        for server_name in capability_plan.mcp_server_names:
            try:
                register_mcp_server_tools(agent, [server_name], settings=mcp_settings)
            except McpServerLoadError as exc:
                report_mcp_load_failure(agent, exc, phase="list_tools", server=server_name)
        if filtered_tool_names:
            filter_registered_agent_tools(agent, filtered_tool_names)

        if effective_system_prompt:
            has_system = any((msg or {}).get("role") == "system" for msg in getattr(agent, "messages", []) or [])
            if not has_system:
                agent.Message("system", effective_system_prompt)
        if not uses_responses_api_context(agent):
            resolved_instruction = effective_instruction(agent, run_request.instruction)
            if resolved_instruction:
                agent.Message(instruction_role, resolved_instruction, persist=False)
        if capability_mode(run_mode):
            bind_group_tools(agent, node_directory=agent_dir,
                             node_id=run_request.agent_id, role=instruction_role,
                             access_role="nondeveloper" if is_nondeveloper_context(ctx) else "developer")
            prepare_node_memory(
                agent, node_dir=agent_dir, graph_id=run_request.graph_id,
                node_id=run_request.agent_id, provider_id=run_request.provider_id,
                role=instruction_role, active_trace=task_id,
            )
        if capability_plan.mcp_server_names:
            inject_mcp_server_context(
                agent,
                list(capability_plan.mcp_server_names),
                settings=mcp_settings,
                role=instruction_role,
            )
        self._inject_configured_skills(
            agent,
            {"skills": list(capability_plan.skill_names)},
            node_id=run_request.agent_id,
            extra_skills=eager_skill_definitions,
            role=instruction_role,
        )
        bind_deferred_skills(
            agent,
            deferred_skill_definitions,
            role=instruction_role,
            mcp_settings=mcp_settings,
        )
        goal_context = node_goal_context(run_request.config_data or ctx)
        if goal_context:
            agent.Message("user", goal_context, persist=False)
        runtime_event_context = runtime_event_context_from_context(ctx)
        for fragment in runtime_event_context:
            agent.Message(fragment["role"], fragment["content"], persist=False)

        restart_recovery_context = render_restart_recovery_context(ctx.get("restart_recovery"))
        user_content = build_agent_user_content(run_request.provider_id, run_mode, input_message, resolved_public_base_url)
        if capability_mode(run_mode):
            context_settings = ConversationSettings.from_config(_workspace_config())
            def compaction_tracker_factory(model_id):
                return ProviderRequestTracker(on_completion=build_agent_gateway_usage_recorder(
                    workspace_root=get_workspace_root(), client_ip=str(ctx.get("access_ip") or ""),
                    task_id=f"{task_id}:context", model_id=model_id,
                ))
            # Persistent conversation history owns cross-input restoration. In-run provider compaction
            # may still operate, but must not reinject an unrelated previous task ledger checkpoint.
            agent._session_context_checkpoint_restored = True
            for history_message in load_agent_history_messages(
                memory_path=memory_path,
                messages_path=self._resolve_messages_path(ctx),
                current_message=input_message,
                provider_id=run_request.provider_id,
                public_base_url=resolved_public_base_url,
                settings=context_settings, historical_evidence_role=instruction_role,
                graph_id=run_request.graph_id, node_id=run_request.agent_id,
                cancel_source=cancel_source, tracker_factory=compaction_tracker_factory,
            ):
                agent.Message(history_message["role"], history_message["content"], persist=False)

        if restart_recovery_context:
            agent.Message(instruction_role, restart_recovery_context, persist=False)
        agent.Message("user", user_content, persist=False)
        tool_stats_recorder = ToolCallStatsRecorder(
            provider_id=run_request.provider_id,
            graph_id=run_request.graph_id,
            node_id=run_request.agent_id,
        )
        stream_runtime = AgentStreamRuntime(
            stream_callback(ctx),
            tool_event_callback=tool_stats_recorder.handle,
        )

        start_time = time.monotonic()
        raise_if_cancel_requested(cancel_source)
        provider_request_tracker.reset()
        response = stream_runtime.send(
            agent,
            AgentSendContext(stream_handler=stream_runtime.on_stream_delta,
                             thinking_stream_handler=stream_runtime.on_thinking_delta),
        )
        min_delay_ms = _resolved_agent_node_settings().min_send_delay_ms
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
        response_structured_result = getattr(agent, "_last_responses_structured_result", None)
        response_for_message = merge_structured_response(response, response_structured_result)
        provider_requests = provider_request_tracker.snapshot()
        response_for_message = stream_runtime.attach_runtime_tool_calls(response_for_message)
        metadata_source = response_for_message
        if provider_requests:
            metadata_source = (
                {**response_for_message, "provider_requests": provider_requests}
                if isinstance(response_for_message, dict)
                else {"provider_requests": provider_requests}
            )
        output_message = build_agent_output_message(response_for_message)
        output_message = append_channel_meta(output_message, channel_meta_parts)
        final_metadata_message = build_response_metadata_message(
            metadata_source,
            scope="final_assistant",
            target_message_id=output_message.get("id"),
            fields=("server_tool_calls", "citations", "response_metadata"),
        )
        run_metadata_message = build_response_metadata_message(
            metadata_source,
            scope="agent_run",
            target_message_id=output_message.get("id"),
            fields=("provider_requests",),
        )
        final_text = envelope_text(output_message).strip()
        stream_runtime.emit_done(final_text, structured_result=response_for_message)
        result = {
            "display": envelope_text(output_message),
            "display_message": output_message,
            "routes": [{"output_index": 0, "payload": output_message}],
        }
        memory_sidecars = [item for item in (final_metadata_message, run_metadata_message) if item is not None]
        if memory_sidecars:
            result["memory_sidecars"] = memory_sidecars
        return result
