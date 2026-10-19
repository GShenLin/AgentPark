from __future__ import annotations

from contextlib import contextmanager
import json
import os

from src.harness.responses_gateway import HarnessResponsesGateway
from src.file_transaction import atomic_write_text
from src.harness.config import load_cli_request
from src.harness.contracts import HarnessContext
from src.harness.execution import execution_session


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
    with execution_session(harness_id, request.binding.provider_id, request, context) as events:
        gateway = HarnessResponsesGateway.instance()
        lease = gateway.register(request.binding.provider_id, model=request.binding.model_id,
                                 reasoning_effort=request.reasoning_effort if harness_id in {"openclaw", "minimax_code"} else "")
        try:
            env = {**os.environ, "AGENTPARK_HARNESS_TOKEN": lease.token}
            yield request, lease, env, events
        finally:
            gateway.release(lease.token)
