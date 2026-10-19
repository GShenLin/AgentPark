"""Runtime-owned continuation after a failed stream with dispatched tools."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.providers.openai_retry_policy import OpenAIRetryPolicy, OpenAIRetryState
from src.providers.responses_item_runtime import ResponsesItemLevelToolRunner
from src.providers.responses_stream_recovery import ResponsesToolsInterrupted
from src.providers.tool_call_execution import ToolCallItem
from src.tool.tool_call_protocol import ToolCallExecution, to_openai_tool_call


@dataclass(frozen=True)
class RecoveredToolResults:
    calls: list[ToolCallItem]
    executions: list[ToolCallExecution]
    continuation_items: list[dict[str, Any]]
    notice: dict[str, Any]
    response_id: str


class ResponsesToolRecovery:
    def __init__(self) -> None:
        self._budget: OpenAIRetryState | None = None

    def recover(self, runtime, runner: ResponsesItemLevelToolRunner,
                error: ResponsesToolsInterrupted) -> RecoveredToolResults:
        if self._budget is None:
            self._budget = OpenAIRetryState(OpenAIRetryPolicy.from_config(runtime.config), scope="stream")
        runtime._record_provider_failure(error, terminal=False)
        runtime._emit_responses_notice(stage="openai_responses_tool_recovery_started", payload={
            "response_id": runner.response_id, "error": str(error), "original_request_replayed": False,
        })
        runtime.AssistantProgress("模型响应流中断；正在保留并收集已启动工具的结果，原请求不会重放。")
        try:
            calls, executions = runner.collect_started_tools()
            if not calls or len(calls) != len(executions):
                raise RuntimeError("Cannot recover stream: dispatched tool results are incomplete")
            continuation = runtime._responses_continuation_input_items(
                {"output": runner.completed_output}, calls,
            )
            # A timed-out/cancelled worker may still have side effects. Do not
            # let another model request decide to repeat an uncertain operation.
            uncertain = [e.call_id for e in executions if e.status in {"timeout", "cancelled"}]
            decision = self._budget.next_retry() if error.retryable and not uncertain else None
            if decision is None:
                runtime.Message("assistant", None, tool_calls=[to_openai_tool_call(c) for c in calls])
                runtime._build_responses_followup_items(executions)
                reason = (f"Uncertain tool outcomes: {uncertain}" if uncertain
                          else "Stream recovery not permitted or recovery budget exhausted")
                raise RuntimeError(f"{reason}; completed tool results preserved. {error}") from error
            notice = {
                "type": "message", "role": "developer",
                "content": [{"type": "input_text", "text": (
                    "The preceding provider response stream failed and was not completed. "
                    "The recorded tool calls were already dispatched; their results follow in this context. "
                    "Continue from these results. Do not repeat operations merely to recover the failed stream. "
                    f"Transport failure: {error.error}"
                )}],
            }
            runtime._emit_responses_notice(stage="openai_responses_tool_recovery_ready", payload={
                "response_id": runner.response_id, "call_ids": [c.call_id for c in calls],
                "attempt": decision.attempt, "max_recoveries": decision.max_retries,
                "response_status": "failed", "next_action": "continue_with_tool_results",
            })
            return RecoveredToolResults(calls, executions, continuation, notice, runner.response_id)
        except BaseException as exc:
            runner.abort(reason="recovery_failed", error=str(exc))
            runtime._record_provider_failure(exc)
            raise
