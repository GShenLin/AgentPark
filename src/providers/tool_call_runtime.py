from src.providers.tool_call_execution import execute_tool_call_envelopes_parallel
from src.providers.tool_loop_guard import ToolLoopGuard
from src.providers.tool_loop_guard import build_tool_loop_blocked_execution
from src.service_host import HostBoundService


class ToolCallExecutionMixin:
    def _reset_tool_call_loop_guard(self) -> None:
        self._tool_loop_guard = ToolLoopGuard()

    def _execute_tool_call_envelopes_parallel(self, tool_calls):
        if not tool_calls:
            return []
        if not isinstance(tool_calls, list):
            return execute_tool_call_envelopes_parallel(
                tool_calls=tool_calls,
                execute_tool_call=self.tools.execute_tool_call,
                execute_tasks_parallel_ordered=self._execute_tasks_parallel_ordered,
            )
        results = [None] * len(tool_calls) if isinstance(tool_calls, list) else []
        executable_calls = []
        executable_positions = []
        guard = self._tool_loop_guard_instance()
        for index, call in enumerate(tool_calls if isinstance(tool_calls, list) else []):
            decision = guard.inspect_and_record(call)
            if decision.blocked:
                results[index] = build_tool_loop_blocked_execution(call, decision)
                self._emit_tool_loop_blocked_notice(call, decision)
                continue
            executable_calls.append(call)
            executable_positions.append(index)

        executed = execute_tool_call_envelopes_parallel(
            tool_calls=executable_calls,
            execute_tool_call=self.tools.execute_tool_call,
            execute_tasks_parallel_ordered=self._execute_tasks_parallel_ordered,
        )
        for position, execution in zip(executable_positions, executed):
            results[position] = execution
        completed_results = [item for item in results if item is not None]
        return completed_results

    def _tool_loop_guard_instance(self):
        guard = getattr(self, "_tool_loop_guard", None)
        if not isinstance(guard, ToolLoopGuard):
            guard = ToolLoopGuard()
            self._tool_loop_guard = guard
        return guard

    def _emit_tool_loop_blocked_notice(self, call, decision) -> None:
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if not callable(emitter):
            return
        import json

        emitter(
            message=json.dumps(
                {
                    "policy": decision.policy,
                    "tool": call.name,
                    "call_id": call.call_id,
                    "previous_call_id": decision.previous_call_id,
                    "reason": decision.reason,
                    "signature": decision.signature,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            stage="tool_call_loop_blocked",
        )


class ToolCallExecutionRuntime(ToolCallExecutionMixin, HostBoundService):
    pass
