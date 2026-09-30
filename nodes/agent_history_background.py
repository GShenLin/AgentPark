"""Prepare ordinary Agent conversation checkpoints after completed output is persisted."""
from __future__ import annotations

import time
from types import SimpleNamespace

from nodes.agent_gateway_usage import build_agent_gateway_usage_recorder
from nodes.agent_history import load_agent_history_messages
from nodes.agent_node_modes import capability_mode, resolve_input_support_mode
from nodes.agent_provider_runtime import resolve_instruction_role
from src.config_loader import ConfigLoader
from src.conversation_context import jobs
from src.conversation_context.settings import ConversationSettings
from src.media_resource_utils import resolve_public_base_url
from src.providers.provider_request_usage import ProviderRequestTracker
from src.workspace_settings import get_workspace_root


def schedule_agent_history_compaction(*, context: dict, config: dict, input_message: dict,
                                      output_message: dict, log_event):
    if config.get("type_id") != "agent_node":
        return None
    # Snapshot only task identity/configuration; history is bounded by this persisted output.
    graph_id, node_id = context["graph_id"], context["node_instance_id"]
    trace_id = context["task_id"]
    memory_path, messages_path = context["memory_path"], context["messages_path"]
    boundary = output_message["id"]
    provider_id = str(config.get("provider_id") or "")
    public_base_url = str(config.get("public_base_url") or "")
    client_ip = str(context.get("access_ip") or "")

    def check():
        started = time.monotonic()
        def emit(stage, **details):
            log_event(graph_id, stage, node_instance_id=node_id, node_type_id="agent_node",
                      trace_id=trace_id, through_message_id=boundary, **details)

        emit("conversation_compaction_check_started")
        try:
            loader = ConfigLoader()
            provider = loader.get_provider_config(provider_id)
            if not capability_mode(resolve_input_support_mode(provider.get("supportmode"), input_message)):
                emit("conversation_compaction_check_skipped", reason="not_conversation_mode")
                return
            settings = ConversationSettings.from_config(loader.get_workspace_config())
            def tracker_factory(model_id):
                return ProviderRequestTracker(on_completion=build_agent_gateway_usage_recorder(
                    workspace_root=get_workspace_root(), client_ip=client_ip,
                    task_id=f"{trace_id}:context", model_id=model_id,
                ))
            load_agent_history_messages(
                memory_path=memory_path, messages_path=messages_path, current_message=None,
                provider_id=provider_id, public_base_url=resolve_public_base_url(public_base_url, provider_id),
                settings=settings,
                historical_evidence_role=resolve_instruction_role(SimpleNamespace(config=provider)),
                graph_id=graph_id, node_id=node_id, tracker_factory=tracker_factory,
                through_message_id=boundary,
                prepare_checkpoint=True,
            )
            emit("conversation_compaction_check_completed", duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            emit("conversation_compaction_check_failed", error=f"{type(exc).__name__}: {exc}",
                 duration_ms=int((time.monotonic() - started) * 1000))
            raise

    return jobs.coordinator.schedule(messages_path, check)
