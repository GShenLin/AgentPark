"""Agent-owned tool executions with resumable, non-destructive reporting waits."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from datetime import datetime, timedelta, timezone
import math
import threading
import time
import uuid

from src.runtime_cancellation import (
    CancellationRequested, CancellationSignal, combine_cancel_sources,
    is_cancel_requested, tool_call_cancellation_scope,
)
from .tool_invocation import ToolInvocationContractError
from .tool_execution_result import ToolExecutionResult, build_error_result, normalize_tool_execution_result

_CURRENT_TASK = ContextVar("agentpark_tool_task", default=None)
_BIND_LOCK = threading.Lock()


def report_tool_progress(progress, *, request_report=False):
    task = _CURRENT_TASK.get()
    if task is not None:
        with task.condition:
            task.progress = dict(progress)
            if request_report:
                task.report_requested = True
            task.condition.notify_all()


def current_tool_task():
    return _CURRENT_TASK.get()


def validate_wait_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 3600:
        raise ValueError("wait_seconds must be a finite number between 0 and 3600")
    return float(value)


class ToolTask:
    def __init__(self, *, tool_name, agent, cancel_source, operation):
        self.task_id = uuid.uuid4().hex
        self.tool_name = tool_name
        self.started = time.monotonic()
        self.condition = threading.Condition()
        self.done = threading.Event()
        self.cancel = CancellationSignal()
        self.cancel_source = combine_cancel_sources(cancel_source, self.cancel)
        self.result = None
        self.progress = {}
        self.report_requested = False
        self.next_report_at = None
        self.wait_seconds = None
        self.completion_callbacks = []
        context = copy_context()

        def run():
            token = _CURRENT_TASK.set(self)
            try:
                from src.remote_workspace.device_state import execution_operation
                with execution_operation(agent, tool_name), tool_call_cancellation_scope(self.cancel_source):
                    result = normalize_tool_execution_result(operation(), tool_name=tool_name)
            except CancellationRequested as exc:
                result = build_error_result("stopped", tool_name=tool_name, error=str(exc))
            except ToolInvocationContractError as exc:
                result = build_error_result("invalid_arguments", tool_name=tool_name, error=str(exc))
            except Exception as exc:
                result = build_error_result("exception", tool_name=tool_name, error=f"{type(exc).__name__}: {exc}")
            finally:
                _CURRENT_TASK.reset(token)
            with self.condition:
                self.result = result
                self.done.set()
                callbacks = list(self.completion_callbacks)
                self.completion_callbacks.clear()
                self.condition.notify_all()
            for callback in callbacks:
                callback(result)

        self.worker = threading.Thread(target=lambda: context.run(run), daemon=True, name=f"tool-{tool_name}")

    def on_completed(self, callback):
        with self.condition:
            if not self.done.is_set():
                self.completion_callbacks.append(callback)
                return
            result = self.result
        callback(result)

    def snapshot(self):
        with self.condition:
            if self.done.is_set():
                return self.result
            payload = {
                "status": "running", "task_id": self.task_id, "tool": self.tool_name,
                "finished": False, "elapsed_seconds": round(time.monotonic() - self.started, 3),
                "cancel_requested": is_cancel_requested(self.cancel_source),
                "progress": dict(self.progress), "next_report_at": self.next_report_at,
                "wait_seconds": self.wait_seconds,
                "continuation": {
                    "tool": "wait_tool_task", "arguments": {"task_id": self.task_id, "wait_seconds": 30},
                    "instruction": "Still running. Do not rerun the original tool. Choose wait_seconds for the next report, or explicitly stop_tool_task. Wait until completion before using its result.",
                },
            }
            return ToolExecutionResult(status="running", result=payload, tool_name=self.tool_name)

    def wait(self, seconds, *, cancel_source=None, initial=False):
        if seconds is not None:
            if initial:
                if isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
                    raise ValueError("Reporting interval must be finite and non-negative")
            else:
                seconds = validate_wait_seconds(seconds)
        deadline = None if seconds is None else time.monotonic() + seconds
        with self.condition:
            self.wait_seconds = seconds
            self.next_report_at = None if seconds is None else (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
            if not initial:
                self.report_requested = False
            while not self.done.is_set():
                if is_cancel_requested(cancel_source):
                    self.cancel.set()
                    self.condition.wait(0.5)
                    if not self.done.is_set():
                        return build_error_result("cancellation_failed", tool_name=self.tool_name,
                                                  error="Cancellation requested; task has not stopped yet.",
                                                  result={"task_id": self.task_id, "finished": False})
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if (remaining is not None and remaining <= 0) or (initial and self.report_requested):
                    break
                self.condition.wait(0.05 if remaining is None else min(0.05, remaining))
            return self.snapshot()


class ToolTaskRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self.tasks = {}
        self.closed = False

    def start(self, **kwargs):
        with self.lock:
            if self.closed:
                raise ValueError("Agent run has ended")
            if sum(not task.done.is_set() for task in self.tasks.values()) >= 32:
                raise ValueError("Too many running tool tasks (maximum 32)")
            if len(self.tasks) >= 256:
                completed = next((key for key, task in self.tasks.items() if task.done.is_set()), None)
                if completed is not None:
                    del self.tasks[completed]
            task = ToolTask(**kwargs)
            self.tasks[task.task_id] = task
            try:
                task.worker.start()
            except BaseException:
                del self.tasks[task.task_id]
                raise
            return task

    def get(self, task_id):
        with self.lock:
            if not isinstance(task_id, str) or task_id not in self.tasks:
                raise ValueError("Unknown tool task for this Agent run")
            return self.tasks[task_id]

    def close(self):
        with self.lock:
            self.closed = True
            tasks = list(self.tasks.values())
        for task in tasks:
            if not task.done.is_set():
                task.cancel.set()
        deadline = time.monotonic() + 5
        for task in tasks:
            task.done.wait(max(0, deadline - time.monotonic()))
        running = [task.task_id for task in tasks if not task.done.is_set()]
        if running:
            raise RuntimeError("Tool tasks did not stop during run cleanup: " + ", ".join(running))


def task_registry_for(agent):
    if agent is None:
        raise ValueError("Tool tasks require an owning Agent")
    with _BIND_LOCK:
        registry = getattr(agent, "_tool_task_registry", None)
        if registry is None:
            registry = ToolTaskRegistry()
            agent._tool_task_registry = registry
        return registry


@contextmanager
def tool_task_scope(agent):
    with _BIND_LOCK:
        previous = getattr(agent, "_tool_task_registry", None)
        if previous is not None and previous.closed:
            agent._tool_task_registry = ToolTaskRegistry()
    try:
        yield
    finally:
        registry = getattr(agent, "_tool_task_registry", None)
        if registry is not None:
            registry.close()
