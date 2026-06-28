import queue
import threading
from collections.abc import Callable
from typing import Any

from src.value_parsing import parse_float_value


def build_mock_plan(mock_actions: list, step_index: int) -> str:
    if step_index - 1 < 0 or step_index - 1 >= len(mock_actions):
        return "Thought: mock_actions exhausted\nAction: finished(content='mock_actions exhausted')"
    item = mock_actions[step_index - 1]
    if isinstance(item, str):
        action_text = item.strip()
        if action_text.lower().startswith("action:"):
            return f"Thought: mock\n{action_text}"
        return f"Thought: mock\nAction: {action_text}"
    if isinstance(item, dict):
        thought = str(item.get("thought") or "mock")
        action = str(item.get("action") or "")
        if not action:
            action = "finished(content='mock empty action')"
        return f"Thought: {thought}\nAction: {action}"
    return "Thought: mock invalid item\nAction: finished(content='mock invalid item')"


def run_with_timeout(fn: Callable[[], Any], timeout_seconds: object) -> Any:
    timeout = parse_float_value(timeout_seconds, default=0.0)
    if timeout <= 0:
        return fn()

    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def _target() -> None:
        try:
            result_queue.put(("ok", fn()))
        except Exception as e:
            result_queue.put(("error", e))

    worker = threading.Thread(target=_target, daemon=True, name="gui-agent-call")
    worker.start()
    worker.join(timeout=timeout)
    if worker.is_alive():
        raise TimeoutError(f"call timeout after {timeout:.1f}s")
    if result_queue.empty():
        raise RuntimeError("call finished without result")
    state, payload = result_queue.get()
    if state == "error":
        if isinstance(payload, Exception):
            raise payload
        raise RuntimeError(str(payload))
    return payload
