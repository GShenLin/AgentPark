import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class GraphExecutionTask:
    task_id: str
    node_id: str
    trace_id: str
    future: Future
    thread: threading.Thread
    started_at: float = field(default_factory=time.time)


class GraphExecutor:
    def __init__(self, graph_id: str) -> None:
        self.graph_id = graph_id
        self._sequence = 0
        self._lock = threading.Lock()

    def submit(self, task_id: str, node_id: str, trace_id: str, func: Callable[[], None]) -> GraphExecutionTask:
        future: Future = Future()
        with self._lock:
            self._sequence += 1
            sequence = self._sequence

        def run() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(func())
            except BaseException as exc:
                future.set_exception(exc)

        thread = threading.Thread(
            target=run,
            daemon=True,
            name=f"graph-executor-{self.graph_id}-{node_id}-{sequence}",
        )
        thread.start()
        return GraphExecutionTask(
            task_id=task_id,
            node_id=node_id,
            trace_id=trace_id,
            future=future,
            thread=thread,
        )


@dataclass
class GraphRunnerState:
    scheduler_thread: threading.Thread | None
    stop: threading.Event
    wake: object
    executor: GraphExecutor
    active_tasks: dict[str, GraphExecutionTask] = field(default_factory=dict)
    active_lock: threading.Lock = field(default_factory=threading.Lock)
    ready_pending_count: int = 0
