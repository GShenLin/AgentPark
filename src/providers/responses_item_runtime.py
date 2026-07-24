from __future__ import annotations

from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.providers.responses_stream_events import ResponsesOutputItemDone
from src.providers.responses_stream_events import ResponsesStreamEvent
from src.providers.tool_call_execution import execute_tool_call_items_parallel
from src.providers.tool_call_execution import ToolCallItem
from src.tool.tool_call_protocol import build_tool_call_parse_error_execution
from src.tool.tool_call_protocol import ToolCallExecution
from src.tool.tool_call_protocol import ToolCallParseFailure


class ResponsesItemLevelToolRunner:
    def __init__(self, runtime: Any, *, run_tools: bool) -> None:
        self._runtime = runtime
        self._run_tools = bool(run_tools)
        gate_active = getattr(runtime, "_tool_context_compaction_gate_active_now", None)
        self._defer_tool_execution = bool(callable(gate_active) and gate_active())
        self._executor: ThreadPoolExecutor | None = None
        self._items_by_call_id: dict[str, ToolCallItem] = {}
        self._futures_by_call_id: dict[str, Future[ToolCallExecution]] = {}
        self._executions_by_call_id: dict[str, ToolCallExecution] = {}
        self._aborted = False

    def handle_event(self, event: ResponsesStreamEvent) -> None:
        if not isinstance(event, ResponsesOutputItemDone) or event.function_call is None:
            return
        tool_items = self._parse_output_item(event.item)
        if not tool_items:
            raise RuntimeError("item-level Responses stream produced an unparseable function_call item")
        for item in tool_items:
            call_id = str(getattr(item, "call_id", "") or "").strip()
            if not call_id:
                raise RuntimeError("item-level Responses stream produced a function_call without call_id")
            self._items_by_call_id[call_id] = item
            if self._run_tools and not self._defer_tool_execution:
                self._start_tool_item(item)

    def wait_for_executions(self, function_calls: list[ToolCallItem]) -> list[ToolCallExecution]:
        if self._aborted:
            raise RuntimeError("item-level Responses tool runner was aborted before tool results were collected")
        if self._defer_tool_execution:
            return execute_tool_call_items_parallel(
                tool_call_items=function_calls,
                execute_tool_call_envelopes=self._runtime._execute_tool_call_envelopes_parallel,
            )
        executions: list[ToolCallExecution] = []
        for call in function_calls if isinstance(function_calls, list) else []:
            call_id = str(getattr(call, "call_id", "") or "").strip()
            if not call_id:
                raise RuntimeError("item-level Responses continuation requires function_call call_id")
            if call_id not in self._items_by_call_id:
                self._items_by_call_id[call_id] = call
                if self._run_tools:
                    self._start_tool_item(call)
            execution = self._execution_for_call_id(call_id)
            if execution is not None:
                executions.append(execution)
        return executions

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def abort(self, *, reason: str, error: str = "") -> dict[str, Any]:
        self._aborted = True
        cancelled = 0
        running = 0
        done = 0
        for future in self._futures_by_call_id.values():
            if future.done():
                done += 1
            elif future.cancel():
                cancelled += 1
            else:
                running += 1
        summary = {
            "reason": str(reason or "aborted"),
            "error": str(error or ""),
            "tool_call_count": len(self._items_by_call_id),
            "future_count": len(self._futures_by_call_id),
            "done_count": done,
            "cancelled_count": cancelled,
            "running_count": running,
            "call_ids": sorted(self._items_by_call_id.keys()),
        }
        emitter = getattr(self._runtime, "_emit_responses_item_level_abort", None)
        if callable(emitter) and (self._items_by_call_id or self._futures_by_call_id):
            emitter(summary)
        self.close()
        return summary

    def _parse_output_item(self, item: dict[str, Any]) -> list[ToolCallItem]:
        _content, function_calls, _response_id = self._runtime._parse_responses_output_envelopes({"output": [item]})
        return function_calls

    def _start_tool_item(self, item: ToolCallItem) -> None:
        call_id = str(getattr(item, "call_id", "") or "").strip()
        if isinstance(item, ToolCallParseFailure):
            self._executions_by_call_id[call_id] = build_tool_call_parse_error_execution(item)
            return
        if call_id in self._futures_by_call_id or call_id in self._executions_by_call_id:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._resolve_max_workers())
        self._futures_by_call_id[call_id] = self._executor.submit(self._execute_tool_item, item)

    def _execution_for_call_id(self, call_id: str) -> ToolCallExecution | None:
        execution = self._executions_by_call_id.get(call_id)
        if execution is not None:
            return execution
        future = self._futures_by_call_id.get(call_id)
        if future is None:
            return None
        execution = future.result()
        self._executions_by_call_id[call_id] = execution
        return execution

    def _execute_tool_item(self, item: ToolCallItem) -> ToolCallExecution:
        executions = execute_tool_call_items_parallel(
            tool_call_items=[item],
            execute_tool_call_envelopes=self._runtime._execute_tool_call_envelopes_parallel,
        )
        if not executions:
            raise RuntimeError("item-level Responses tool execution returned no result")
        return executions[0]

    def _resolve_max_workers(self) -> int:
        resolver = getattr(self._runtime, "_resolve_parallel_workers", None)
        if callable(resolver):
            return max(1, int(resolver(64)))
        return 1
