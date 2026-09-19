from __future__ import annotations

import os

from nodes.agent_provider_runtime import stream_callback
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.tool_stats_store import ToolCallStatsRecorder

from nodes.codex_node.config import load_codex_node_run_request
from nodes.codex_node.runtime.live_bridge import CodexLiveBridge
from nodes.codex_node.runtime.session_manager import CodexSessionManager
from nodes.codex_node.runtime.session_manager import CodexSessionSpec
from nodes.codex_node.runtime.thread_state import THREAD_STATE_FILENAME
from nodes.codex_node.runtime.thread_state import session_runtime_key

from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.provider_binding import ProviderBinding
from src.harness.install_manager import resolve_command

class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        ctx = context.values
        config_path = context.config_path
        node_directory = context.node_directory
        request = load_codex_node_run_request(ctx, config_path=config_path)
        access_role = str(ctx.get("access_role") or "").strip().lower()
        sandbox = "read-only" if access_role == "nondeveloper" else request.sandbox
        binding = ProviderBinding.resolve(request.provider_id, request.model_id)
        model = binding.model_id
        if request.web_search != "disabled" and binding.protocol != "responses":
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
                command=resolve_command("codex", request.command),
                cwd=request.cwd,
                sandbox=sandbox,
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

        return HarnessResult(final_text, structured_result)
