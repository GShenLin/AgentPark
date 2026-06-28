from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool.tool_call_protocol import ToolCallExecution
from src.tool.tool_call_protocol import ToolCallParseFailure
from src.tool.tool_call_protocol import build_tool_call_error_execution
from src.tool.tool_call_protocol import build_tool_call_parse_error_execution
from src.tool.tool_call_protocol import from_openai_tool_call
from src.tool.tool_call_protocol import from_openai_tool_call_parse_failure


ToolCallItem = ToolCallEnvelope | ToolCallParseFailure


def parse_openai_tool_call_items(tool_calls: Any, *, provider: str) -> list[ToolCallItem]:
    items: list[ToolCallItem] = []
    for item in tool_calls if isinstance(tool_calls, list) else []:
        try:
            call = from_openai_tool_call(item, provider=provider)
        except ValueError as exc:
            failure = from_openai_tool_call_parse_failure(item, provider=provider, error=exc)
            if failure is not None:
                items.append(failure)
            continue
        if call is not None:
            items.append(call)
    return items


def execute_tool_call_items_parallel(
    *,
    tool_call_items: list[ToolCallItem],
    execute_tool_call_envelopes: Callable[[list[ToolCallEnvelope]], list[ToolCallExecution]],
) -> list[ToolCallExecution]:
    results: list[ToolCallExecution | None] = [None] * len(tool_call_items)
    valid_calls: list[ToolCallEnvelope] = []
    valid_positions: list[int] = []
    for index, item in enumerate(tool_call_items):
        if isinstance(item, ToolCallParseFailure):
            results[index] = build_tool_call_parse_error_execution(item)
            continue
        if not isinstance(item, ToolCallEnvelope):
            raise TypeError("execute_tool_call_items_parallel requires ToolCallEnvelope or ToolCallParseFailure items")
        valid_calls.append(item)
        valid_positions.append(index)

    valid_results = execute_tool_call_envelopes(valid_calls)
    for position, execution in zip(valid_positions, valid_results):
        results[position] = execution
    return [item for item in results if item is not None]


def execute_tool_call_envelopes_parallel(
    *,
    tool_calls: list[ToolCallEnvelope] | None,
    execute_tool_call: Callable[[ToolCallEnvelope], ToolCallExecution],
    execute_tasks_parallel_ordered: Callable[..., list[ToolCallExecution]],
) -> list[ToolCallExecution]:
    if not tool_calls:
        return []
    if not isinstance(tool_calls, list) or not all(isinstance(item, ToolCallEnvelope) for item in tool_calls):
        raise TypeError("execute_tool_call_envelopes_parallel requires a list of ToolCallEnvelope items")

    return execute_tasks_parallel_ordered(
        tasks=tool_calls,
        run_task=execute_tool_call,
        task_to_meta=_tool_call_meta,
        build_error_result=_build_tool_worker_error,
        build_timeout_result=_build_tool_worker_timeout,
    )


def _tool_call_meta(tool_call: ToolCallEnvelope) -> tuple[str, str]:
    return tool_call.name, tool_call.call_id


def _build_tool_worker_error(tool_call: ToolCallEnvelope, error: Exception, _index: int) -> ToolCallExecution:
    return build_tool_call_error_execution(
        tool_call,
        status="error",
        error=f"{type(error).__name__}: {error}",
    )


def _build_tool_worker_timeout(tool_call: ToolCallEnvelope, timeout_seconds: float, _index: int) -> ToolCallExecution:
    return build_tool_call_error_execution(
        tool_call,
        status="timeout",
        error=f"Tool worker exceeded {timeout_seconds:.2f}s.",
    )


__all__ = [
    "ToolCallItem",
    "execute_tool_call_envelopes_parallel",
    "execute_tool_call_items_parallel",
    "parse_openai_tool_call_items",
]
