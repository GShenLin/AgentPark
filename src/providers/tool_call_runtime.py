from src.providers.tool_call_execution import execute_tool_call_envelopes_parallel
from src.service_host import HostBoundService


class ToolCallExecutionMixin:
    def _execute_tool_call_envelopes_parallel(self, tool_calls):
        return execute_tool_call_envelopes_parallel(
            tool_calls=tool_calls,
            execute_tool_call=self.tools.execute_tool_call,
            execute_tasks_parallel_ordered=self._execute_tasks_parallel_ordered,
        )


class ToolCallExecutionRuntime(ToolCallExecutionMixin, HostBoundService):
    pass
