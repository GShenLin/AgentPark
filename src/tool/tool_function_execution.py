from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import raise_if_cancel_requested
from src.runtime_cancellation import tool_call_cancellation_scope

from .tool_execution_result import build_error_result
from .tool_execution_result import build_cancellation_failed_result
from .tool_execution_result import normalize_tool_execution_result
from .tool_execution_result import ToolExecutionResult
from .tool_invocation import invoke_tool_function
from .tool_invocation import ToolInvocationContractError
from .tool_event_protocol import now_monotonic


_CANCELLATION_JOIN_GRACE_SECONDS = 0.5


def execute_local_tool_function(
    *,
    func: Callable[..., Any],
    args: Any,
    agent: object,
    tool_name: str,
    timeout_seconds: float | None,
    cancel_source: Any,
) -> ToolExecutionResult:
    if timeout_seconds is None:
        try:
            with tool_call_cancellation_scope(cancel_source):
                return normalize_tool_execution_result(
                    invoke_tool_function(func, args, agent=agent),
                    tool_name=tool_name,
                )
        except CancellationRequested as exc:
            return build_error_result("stopped", tool_name=tool_name, error=str(exc))
        except ToolInvocationContractError as exc:
            return build_error_result("invalid_arguments", tool_name=tool_name, error=str(exc))
        except Exception as exc:
            return build_error_result(
                "exception",
                tool_name=tool_name,
                error=f"{type(exc).__name__}: {exc}",
            )

    result_queue: queue.Queue[tuple[str, ToolExecutionResult]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            with tool_call_cancellation_scope(cancel_source):
                result_queue.put(
                    (
                        "ok",
                        normalize_tool_execution_result(
                            invoke_tool_function(func, args, agent=agent),
                            tool_name=tool_name,
                        ),
                    )
                )
        except CancellationRequested as exc:
            result_queue.put(
                ("error", build_error_result("stopped", tool_name=tool_name, error=str(exc)))
            )
        except ToolInvocationContractError as exc:
            result_queue.put(
                (
                    "error",
                    build_error_result(
                        "invalid_arguments",
                        tool_name=tool_name,
                        error=str(exc),
                    ),
                )
            )
        except Exception as exc:
            result_queue.put(
                (
                    "error",
                    build_error_result(
                        "exception",
                        tool_name=tool_name,
                        error=f"{type(exc).__name__}: {exc}",
                    ),
                )
            )

    worker = threading.Thread(target=run, daemon=True, name=f"tool-{tool_name}")
    worker.start()
    deadline = now_monotonic() + float(timeout_seconds)
    while worker.is_alive():
        try:
            raise_if_cancel_requested(cancel_source)
        except CancellationRequested as exc:
            worker.join(timeout=_CANCELLATION_JOIN_GRACE_SECONDS)
            if worker.is_alive():
                return build_cancellation_failed_result(tool_name=tool_name)
            return build_error_result("stopped", tool_name=tool_name, error=str(exc))
        remaining = deadline - now_monotonic()
        if remaining <= 0:
            break
        worker.join(timeout=min(0.05, remaining))

    if worker.is_alive():
        return build_error_result(
            "timeout",
            tool_name=tool_name,
            error=f"Tool execution exceeded {timeout_seconds:.2f}s.",
        )
    if result_queue.empty():
        return build_error_result(
            "exception",
            tool_name=tool_name,
            error="Tool worker returned no result.",
        )

    _state, result = result_queue.get()
    return result


__all__ = ["execute_local_tool_function"]
