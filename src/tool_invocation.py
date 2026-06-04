from __future__ import annotations

import inspect
from typing import Any, Callable


class ToolInvocationContractError(TypeError):
    """Raised when a tool function cannot be called through the tool protocol."""


def invoke_tool_function(func: Callable[..., Any], args: Any, *, agent: object) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError) as exc:
        raise ToolInvocationContractError(
            f"Cannot inspect signature for tool function {getattr(func, '__name__', repr(func))}."
        ) from exc

    parameters = signature.parameters
    if isinstance(args, dict):
        if "agent" in parameters and "agent" not in args:
            return func(agent=agent, **args)
        return func(**args)

    if "agent" in parameters:
        return func(agent=agent)
    return func()
