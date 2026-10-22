"""Agent-facing control plane for moving a run between execution workspaces."""
from dataclasses import replace
import os
import uuid
from pydantic import Field
from src.peer_network.remote_contracts import RemoteDescriptor

from src.providers.agent_environment_context import resolve_agent_working_directory
from src.providers.agent_runtime_context import bind_agent_runtime_context, get_agent_runtime_context
from src.providers.curl_transport import CurlHttpTransport
from src.runtime_cancellation import cancel_source_from_agent, raise_if_cancel_requested
from src.tool.tool_json_response import tool_json_payload
from .client import execute_remote_request
from .device_state import device_state, switching_device
from .inspection import WorkspaceInspection, inspect_workspace


class ExecutionDeviceDescriptor(RemoteDescriptor):
    worker_id: str = Field(min_length=1, max_length=198)


def _worker_catalog() -> list[dict]:
    port = str(os.environ.get("AGENTPARK_SERVER_PORT") or "8766")
    response = CurlHttpTransport().request(
        url=f"http://127.0.0.1:{port}/api/remote-workers", timeout_sec=15,
    ).raise_for_status().json()
    if not isinstance(response, dict) or not isinstance(response.get("workers"), list):
        raise ValueError("Invalid remote worker catalog.")
    workers = []
    for item in response["workers"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid remote worker descriptor.")
        # Catalog adds routing metadata to the canonical wire descriptor.
        fields = {key: item[key] for key in ExecutionDeviceDescriptor.model_fields}
        workers.append(ExecutionDeviceDescriptor.model_validate(fields).model_dump())
    return workers


def _current(agent: object) -> dict:
    context = get_agent_runtime_context(agent)
    return {
        "device_id": context.remote_worker_id if context.remote_enabled else "local",
        "working_path": resolve_agent_working_directory(agent),
        "revision": device_state(agent).revision,
        "workspace": dict(context.execution_workspace),
        "scope": "current_run",
    }


def list_execution_devices(agent=None) -> str:
    state = device_state(agent)
    workers = _worker_catalog()
    with state.lock:
        current = _current(agent)
    from src.runtime_environment import get_runtime_environment
    local = get_runtime_environment()
    return tool_json_payload({
        "status": "success", "current": current,
        "devices": [{"device_id": "local", "display_name": "AgentPark host",
                     "online": True, "platform": local.platform, "shell": local.shell,
                     "switch_supported": True}] + [
            {"device_id": worker["worker_id"], "display_name": worker["display_name"],
             "online": worker["online"], "workspace_path": worker["workspace_path"],
             "capabilities": worker["capabilities"],
             "switch_supported": "inspect_workspace" in worker["capabilities"]}
            for worker in workers
        ],
    })


def _inspect(device_id: str, working_path: str, agent=None) -> WorkspaceInspection:
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("device_id must be a non-empty catalog ID or local.")
    if not isinstance(working_path, str) or not working_path.strip():
        raise ValueError("working_path must be an absolute directory on the selected device.")
    if device_id == "local":
        return inspect_workspace(working_path)
    workers = [worker for worker in _worker_catalog() if worker["worker_id"] == device_id]
    if len(workers) != 1:
        raise LookupError("Execution device is not present uniquely in the authorized worker catalog.")
    worker = workers[0]
    if not worker["online"]:
        raise ConnectionError("Execution device is offline.")
    if "inspect_workspace" not in worker["capabilities"]:
        raise RuntimeError("Device needs an AgentPark/Remote update: inspect_workspace is unavailable.")
    result = execute_remote_request({
        "task_id": uuid.uuid4().hex, "worker_id": device_id,
        "tool_name": "inspect_workspace", "working_path": working_path,
        "arguments": {}, "timeout_seconds": 20.0,
    }, cancel_source=cancel_source_from_agent(agent))
    if not isinstance(result, str):
        raise ValueError("Device returned an invalid workspace inspection response.")
    return WorkspaceInspection.model_validate_json(result)


def inspect_execution_workspace(device_id: str, working_path: str, agent=None) -> str:
    device_state(agent)
    inspection = _inspect(device_id, working_path, agent)
    return tool_json_payload({"status": "success", "device_id": device_id,
                              "workspace": inspection.model_dump()})


def switch_execution_device(device_id: str, working_path: str, expected_revision: int, agent=None) -> str:
    with switching_device(agent, expected_revision) as state:
        previous = _current(agent)
        inspection = _inspect(device_id, working_path, agent)
        raise_if_cancel_requested(cancel_source_from_agent(agent))
        context = get_agent_runtime_context(agent)
        updated = replace(context, remote_enabled=device_id != "local",
                          remote_worker_id="" if device_id == "local" else device_id,
                          working_path=inspection.working_path, shell=inspection.shell,
                          execution_workspace=inspection.model_dump())
        with state.lock:
            bind_agent_runtime_context(agent, updated)
            state.revision += 1
            current = _current(agent)
        return tool_json_payload({
            "status": "success", "previous": previous, "current": current,
            "notice": "Execution workspace changed. Use the returned shell, directory and project instructions "
                      "for subsequent workspace tools; previous workspace instructions no longer apply. "
                      "Files and processes were not transferred. Node defaults are unchanged.",
        })


for _tool in (list_execution_devices, inspect_execution_workspace, switch_execution_device):
    _tool.tool_timeout_seconds = 90
    _tool.tool_cooperative_cancellation = True
