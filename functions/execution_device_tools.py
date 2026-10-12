"""Discoverable tool module for the cross-device-workflow skill."""
from src.remote_workspace.device_tools import (
    list_execution_devices, inspect_execution_workspace, switch_execution_device,
)


def _declaration(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False},
    }}


_target = {
    "device_id": {"type": "string", "description": "Exact device_id from list_execution_devices, or local."},
    "working_path": {"type": "string", "description": "Existing absolute directory on that device."},
}
list_execution_devices_declaration = _declaration(
    "list_execution_devices", "List execution devices and the current run's target and revision. "
    "Devices without switch_supported need an update; never substitute another device silently.", {}, [],
)
inspect_execution_workspace_declaration = _declaration(
    "inspect_execution_workspace", "Read the actual shell, platform and project instructions at a device workspace "
    "without changing the current execution target.", _target, list(_target),
)
switch_execution_device_declaration = _declaration(
    "switch_execution_device", "Switch this Agent run's subsequent file/search/patch/command tools to a device "
    "and workspace. Call alone, wait for success, then use the returned environment. "
    "Does not migrate files, processes, memory, browser/MCP tools or node defaults. "
    "Finish active tools and console sessions first. Supports returning to local.",
    {**_target, "expected_revision": {"type": "integer", "minimum": 0}},
    [*_target, "expected_revision"],
)
