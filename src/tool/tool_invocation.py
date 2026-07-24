from __future__ import annotations

import inspect
from typing import Any, Callable


class ToolInvocationContractError(TypeError):
    """Raised when a tool function cannot be called through the tool protocol."""


def _function_name(func: Callable[..., Any]) -> str:
    return str(getattr(func, "__name__", repr(func)))


def _bind_keyword_arguments(
    signature: inspect.Signature,
    func: Callable[..., Any],
    args: dict[str, Any],
    *,
    agent: object,
) -> inspect.BoundArguments:
    invocation_args = dict(args)
    parameters = signature.parameters
    if "agent" in parameters and "agent" not in invocation_args:
        invocation_args["agent"] = agent

    try:
        return signature.bind(**invocation_args)
    except TypeError as exc:
        visible_parameters = [
            name
            for name, parameter in parameters.items()
            if name != "agent"
            and parameter.kind
            not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        ]
        supplied = sorted(str(name) for name in args)
        expected = sorted(visible_parameters)
        raise ToolInvocationContractError(
            f"Invalid arguments for tool {_function_name(func)!r}: {exc}. "
            f"Supplied top-level keys: {supplied}. "
            f"Expected top-level keys: {expected}. "
            "Retry using only the declared top-level keys."
        ) from exc


def invoke_tool_function(func: Callable[..., Any], args: Any, *, agent: object) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError) as exc:
        raise ToolInvocationContractError(
            f"Cannot inspect signature for tool function {_function_name(func)}."
        ) from exc

    parameters = signature.parameters
    if isinstance(args, dict):
        bound = _bind_keyword_arguments(signature, func, args, agent=agent)
        return func(*bound.args, **bound.kwargs)

    if "agent" in parameters:
        return func(agent=agent)
    return func()
