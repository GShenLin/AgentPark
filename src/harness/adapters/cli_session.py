from __future__ import annotations

from contextlib import contextmanager
import json
import os
import threading

from nodes.agent_provider_runtime import stream_callback
from src.harness.responses_gateway import HarnessResponsesGateway
from src.file_transaction import atomic_write_text
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.tool_stats_store import ToolCallStatsRecorder
from src.harness.config import load_cli_request
from src.harness.contracts import HarnessContext
from src.harness.events import HarnessEvents

_LOCK = threading.Lock()
_SESSIONS: dict[str, threading.Lock] = {}


def write_json(path, value: dict) -> None:
    atomic_write_text(str(path), json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_event(line: str) -> dict:
    value = json.loads(line)
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ValueError("Harness event must be an object with a string type.")
    return value


def string_field(event: dict, name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str):
        raise ValueError(f"Harness {event.get('type')} event requires string field {name}.")
    return value


@contextmanager
def cli_session(harness_id: str, context: HarnessContext):
    request = load_cli_request(harness_id, context)
    with _LOCK:
        lock = _SESSIONS.setdefault(str(request.state_dir), threading.Lock())
    while not lock.acquire(timeout=0.1):
        raise_if_cancel_requested(request.cancel_source)
    lease = None
    try:
        gateway = HarnessResponsesGateway.instance()
        raise_if_cancel_requested(request.cancel_source)
        request.state_dir.mkdir(parents=True, exist_ok=True)
        lease = gateway.register(request.binding.provider_id, model=request.binding.model_id,
                                 reasoning_effort=request.reasoning_effort if harness_id == "openclaw" else "")
        env = {**os.environ, "AGENTPARK_HARNESS_TOKEN": lease.token}
        callback = stream_callback(context.values)
        stats = ToolCallStatsRecorder(provider_id=request.binding.provider_id,
                                      graph_id=str(context.values.get("graph_id") or "default"),
                                      node_id=str(context.values.get("node_instance_id") or harness_id))

        def emit(event: dict) -> None:
            if event["type"] in {"tool_call_start", "tool_call_end"}:
                stats.handle(event)
            if callback:
                callback(event)

        events = HarnessEvents(harness_id, request.binding.provider_id, emit)
        yield request, lease, env, events
    finally:
        if lease:
            gateway.release(lease.token)
        lock.release()
