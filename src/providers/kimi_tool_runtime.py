from __future__ import annotations

from src.kimi_model_contract import KIMI_WEB_SEARCH_TOOL_NAME
from src.providers.server_tool_protocol import build_server_tool_activity
from src.providers.tool_call_runtime import ToolCallExecutionRuntime
from src.tool.tool_call_protocol import ToolCallExecution


class KimiToolCallExecutionRuntime(ToolCallExecutionRuntime):
    def _execute_tool_call_envelopes_parallel(self, tool_calls):
        if not isinstance(tool_calls, list):
            return super()._execute_tool_call_envelopes_parallel(tool_calls)

        results: list[ToolCallExecution | None] = [None] * len(tool_calls)
        regular_calls = []
        regular_positions = []
        for index, call in enumerate(tool_calls):
            if call.name == KIMI_WEB_SEARCH_TOOL_NAME:
                results[index] = self._build_kimi_web_search_execution(call)
                continue
            regular_calls.append(call)
            regular_positions.append(index)

        regular_results = super()._execute_tool_call_envelopes_parallel(regular_calls)
        for position, execution in zip(regular_positions, regular_results):
            results[position] = execution
        return [item for item in results if item is not None]

    def _build_kimi_web_search_execution(self, call) -> ToolCallExecution:
        action = {
            key: call.arguments[key]
            for key in ("query", "search_query", "queries")
            if key in call.arguments
        }
        pending = getattr(self.host, "_kimi_pending_web_search_calls", None)
        if not isinstance(pending, dict):
            pending = {}
            setattr(self.host, "_kimi_pending_web_search_calls", pending)
        pending[call.call_id] = action

        event = build_server_tool_activity(
            {
                "type": "web_search_call",
                "id": call.call_id,
                "status": "in_progress",
                "action": action,
            },
            status="in_progress",
            provider="kimi",
        )
        callback = getattr(self, "tool_event_callback", None)
        if event is not None and callable(callback):
            callback(event)

        return ToolCallExecution(
            func_name=call.name,
            call_id=call.call_id,
            cleaned_result=call.arguments_json,
            status="completed",
        )


__all__ = ["KimiToolCallExecutionRuntime"]
