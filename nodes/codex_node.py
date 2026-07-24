from __future__ import annotations

import os

from nodes.agent_message_adapter import append_channel_meta
from nodes.agent_message_adapter import build_response_metadata_message
from nodes.agent_message_adapter import extract_channel_meta
from nodes.agent_provider_runtime import stream_callback
from nodes.base_node import BaseNode
from nodes.codex_node_config import load_codex_node_run_request
from nodes.codex_node_contract import CODEX_CONFIG_DEFAULTS
from nodes.codex_node_contract import CODEX_CONFIG_SCHEMA
from nodes.codex_node_contract import CODEX_INPUT_CAPABILITIES
from nodes.codex_node_contract import CODEX_OUTPUT_CAPABILITIES
from src.codex_runtime.live_bridge import CodexLiveBridge
from src.codex_runtime.session_manager import CodexSessionManager
from src.codex_runtime.session_manager import CodexSessionSpec
from src.codex_runtime.provider_adapter import provider_protocol
from src.codex_runtime.thread_state import THREAD_STATE_FILENAME
from src.codex_runtime.thread_state import session_runtime_key
from src.config_loader import ConfigLoader
from src.message_protocol import build_text_envelope
from src.message_protocol import envelope_text
from src.message_protocol import normalize_envelope
from src.provider_options import build_provider_options_for_support_modes
from src.provider_options import provider_options_include_private
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.tool_stats_store import ToolCallStatsRecorder


_CODEX_PROVIDER_MODES = {"chat", "imagechat"}


class Node(BaseNode):
    name = "Codex"
    description = "启动真实 Codex app-server，并通过 ProviderID 路由模型请求"
    input_capabilities = CODEX_INPUT_CAPABILITIES
    output_capabilities = CODEX_OUTPUT_CAPABILITIES
    config_defaults = CODEX_CONFIG_DEFAULTS
    config_schema = CODEX_CONFIG_SCHEMA
    common_config_defaults = {"working_path": ""}
    common_config_schema = {"working_path": BaseNode.common_config_schema["working_path"]}

    def get_config_schema(self, context: dict | None = None) -> dict:
        schema = super().get_config_schema(context)
        provider_schema = dict(schema.get("provider_id") or {})
        provider_schema["type"] = "select"
        provider_schema["options"] = build_provider_options_for_support_modes(
            _CODEX_PROVIDER_MODES,
            include_private=provider_options_include_private(context),
        )
        schema["provider_id"] = provider_schema
        return schema

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        input_message = normalize_envelope(message, default_role="user")
        text = envelope_text(input_message).strip()
        if not text:
            raise ValueError("Codex node input contains no text or representable resource.")

        explicit_config_path = str(ctx.get("node_config_path") or "").strip()
        if explicit_config_path:
            config_path = os.path.abspath(explicit_config_path)
            node_directory = os.path.dirname(config_path)
        else:
            node_directory = os.path.dirname(self._resolve_memory_path(ctx))
            config_path = os.path.join(node_directory, "config.json")

        request = load_codex_node_run_request(ctx, config_path=config_path)
        provider_config = ConfigLoader().get_provider_config(request.provider_id)
        model = str(provider_config.get("model") or "").strip()
        if not model:
            raise ValueError(f"Provider {request.provider_id!r} has no model.")
        if request.web_search != "disabled" and provider_protocol(provider_config) != "responses":
            raise ValueError("Codex hosted web_search requires a Provider with responsesApi=true.")

        cancel_source = ctx.get("cancel_event") or ctx.get("cancel_check")
        raise_if_cancel_requested(cancel_source)
        tool_stats = ToolCallStatsRecorder(
            provider_id=request.provider_id,
            graph_id=request.graph_id,
            node_id=request.node_id,
        )
        bridge = CodexLiveBridge(
            stream_callback(ctx),
            tool_event_callback=tool_stats.handle,
            provider_id=request.provider_id,
        )
        state_path = os.path.join(node_directory, THREAD_STATE_FILENAME)
        session_key = session_runtime_key(request.graph_id, request.node_id, state_path)
        final_text = CodexSessionManager.instance().run_turn(
            CodexSessionSpec(
                session_key=session_key,
                provider_id=request.provider_id,
                model=model,
                command=request.command,
                cwd=request.cwd,
                sandbox=request.sandbox,
                state_path=state_path,
                developer_instructions=request.instruction,
                reasoning_effort=request.reasoning_effort,
                web_search=request.web_search,
            ),
            text,
            event_handler=bridge.handle,
            cancel_source=cancel_source,
        )
        raise_if_cancel_requested(cancel_source)
        structured_result = bridge.emit_done(final_text)

        output_message = build_text_envelope(final_text, role="assistant")
        output_message = append_channel_meta(output_message, extract_channel_meta(input_message))
        metadata_message = build_response_metadata_message(
            structured_result,
            scope="final_assistant",
            target_message_id=output_message.get("id"),
            fields=("response_metadata",),
        )
        result = {
            "display": envelope_text(output_message),
            "display_message": output_message,
            "routes": [{"output_index": 0, "payload": output_message}],
        }
        if metadata_message is not None:
            result["memory_sidecars"] = [metadata_message]
        return result


__all__ = ["Node"]
