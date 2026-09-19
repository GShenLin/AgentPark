from __future__ import annotations

import os

from nodes.agent_provider_runtime import stream_callback
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.tool_stats_store import ToolCallStatsRecorder

from nodes.claude_node.config import load_claude_node_run_request
from nodes.claude_node.runtime.contracts import ClaudeSessionSpec
from nodes.claude_node.runtime.live_bridge import ClaudeLiveBridge
from nodes.claude_node.runtime.session_manager import ClaudeSessionManager
from nodes.claude_node.runtime.session_state import SESSION_STATE_FILENAME
from nodes.claude_node.runtime.session_state import session_runtime_key

from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.provider_binding import ProviderBinding
from src.harness.install_manager import resolve_command

class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        ctx = context.values
        config_path = context.config_path
        node_directory = context.node_directory
        request = load_claude_node_run_request(ctx, config_path=config_path)
        access_role = str(ctx.get("access_role") or "").strip().lower()
        permission_mode = "plan" if access_role == "nondeveloper" else request.permission_mode
        binding = ProviderBinding.resolve(request.provider_id, request.model_id)
        model = binding.model_id

        cancel_source = ctx.get("cancel_event") or ctx.get("cancel_check")
        raise_if_cancel_requested(cancel_source)
        tool_stats = ToolCallStatsRecorder(
            provider_id=request.provider_id,
            graph_id=request.graph_id,
            node_id=request.node_id,
        )
        bridge = ClaudeLiveBridge(
            stream_callback(ctx),
            tool_event_callback=tool_stats.handle,
            provider_id=request.provider_id,
        )
        state_path = os.path.join(node_directory, SESSION_STATE_FILENAME)
        session_key = session_runtime_key(request.graph_id, request.node_id, state_path)
        final_text = ClaudeSessionManager.instance().run_turn(
            ClaudeSessionSpec(
                session_key=session_key,
                provider_id=request.provider_id,
                model=model,
                command=resolve_command("claude", request.command),
                cwd=request.cwd,
                permission_mode=permission_mode,
                state_path=state_path,
                instruction=request.instruction,
                reasoning_effort=request.reasoning_effort,
            ),
            text,
            event_handler=bridge.handle,
            gateway_observer=bridge.observe_gateway_request,
            cancel_source=cancel_source,
        )
        raise_if_cancel_requested(cancel_source)
        structured_result = bridge.emit_done(final_text)

        return HarnessResult(final_text, structured_result)
