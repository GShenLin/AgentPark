"""Task controls shared by built-in, plugin and MCP tools."""
from src.runtime_cancellation import cancel_source_from_agent
from .tool_tasks import task_registry_for, validate_wait_seconds


def read_tool_task(task_id, agent=None):
    return task_registry_for(agent).get(task_id).snapshot()


def wait_tool_task(task_id, wait_seconds, agent=None):
    seconds = validate_wait_seconds(wait_seconds)
    return task_registry_for(agent).get(task_id).wait(seconds, cancel_source=cancel_source_from_agent(agent))


def stop_tool_task(task_id, agent=None):
    task = task_registry_for(agent).get(task_id)
    task.cancel.set()
    return task.wait(0.5)


TASK_CONTROL_TOOLS = {func.__name__: func for func in (read_tool_task, wait_tool_task, stop_tool_task)}


def control_declarations():
    descriptions = {
        "read_tool_task": "Read current state or final result of a running tool task without waiting or restarting it.",
        "wait_tool_task": "Continue an existing tool task. Choose wait_seconds as the next reporting interval (0-3600 seconds). Return early on completion; otherwise return running state and report timestamp. Expiring a wait NEVER stops execution. Do not repeat the original invocation.",
        "stop_tool_task": "Explicitly request cancellation of a running tool task. If still running, cancellation has not completed; read or wait again to confirm.",
    }
    for name in TASK_CONTROL_TOOLS:
        properties = {"task_id": {"type": "string"}}
        if name == "wait_tool_task":
            properties["wait_seconds"] = {"type": "number", "minimum": 0, "maximum": 3600,
                                           "description": "Seconds until the next status report; choose based on progress."}
        yield {"type": "function", "function": {"name": name, "description": descriptions[name],
               "parameters": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}}
