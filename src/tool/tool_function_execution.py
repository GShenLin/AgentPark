"""Invoke each tool once; reporting deadlines never cancel its worker."""
from .tool_tasks import task_registry_for
from .tool_invocation import invoke_tool_function


def execute_local_tool_function(*, func, args, agent, tool_name, timeout_seconds, cancel_source):
    registry = task_registry_for(agent)
    task = registry.start(
        tool_name=tool_name, agent=agent, cancel_source=cancel_source,
        operation=lambda: invoke_tool_function(func, args, agent=agent),
    )
    return task.wait(timeout_seconds, cancel_source=cancel_source, initial=True)
