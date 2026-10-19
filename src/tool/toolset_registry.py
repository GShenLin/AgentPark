"""Editable toolsets refer to individual, existing Python tool exports.

References are module:function pairs, never nested toolsets. Python remains the
authority for schemas and execution; JSON only controls membership and order.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from src import workspace_settings
from src.tool.tool_load_errors import ToolLoadError
from src.tool.tool_module_loader import get_functions_dir, load_tool_module

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ToolEntry = tuple[dict, Callable]


def toolsets_path() -> str:
    return str(Path(workspace_settings.get_workspace_root()) / "config" / "toolsets.json")


def validate_structure(payload: object) -> dict:
    if not isinstance(payload, dict) or "toolsets" not in payload or set(payload) - {"toolsets", "deleted_toolsets"}:
        raise ValueError("Toolset settings require 'toolsets' and optional 'deleted_toolsets' fields only.")
    sets = payload["toolsets"]
    if not isinstance(sets, dict):
        raise ValueError("toolsets must be an object.")
    deleted = payload.get("deleted_toolsets", [])
    if not isinstance(deleted, list) or any(not isinstance(name, str) or not _IDENTIFIER.fullmatch(name) for name in deleted):
        raise ValueError("deleted_toolsets must be a list of toolset identifiers.")
    if len(deleted) != len(set(deleted)) or set(deleted).intersection(sets):
        raise ValueError("Deleted toolsets must be unique and cannot also appear in toolsets.")
    for name, definition in sets.items():
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
            raise ValueError(f"Invalid toolset identifier: {name!r}")
        if not isinstance(definition, dict) or set(definition) != {"description", "tools"}:
            raise ValueError(f"Toolset {name} requires description and tools fields only.")
        if not isinstance(definition["description"], str) or not isinstance(definition["tools"], list):
            raise ValueError(f"Toolset {name}: description must be text and tools must be a list.")
        seen = set()
        for reference in definition["tools"]:
            split_reference(reference)
            if reference in seen:
                raise ValueError(f"Toolset {name} repeats tool {reference}.")
            seen.add(reference)
    return payload


def split_reference(reference: object) -> tuple[str, str]:
    if not isinstance(reference, str):
        raise ValueError("Tool references must be module:function strings.")
    parts = reference.split(":")
    if len(parts) != 2 or not all(_IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError(f"Invalid tool reference: {reference!r}; expected module:function.")
    return parts[0], parts[1]


def load_toolset_config() -> dict:
    path = Path(toolsets_path())
    if not path.exists():
        return {"toolsets": {}, "deleted_toolsets": []}
    payload = validate_structure(json.loads(path.read_text(encoding="utf-8")))
    return {"toolsets": payload["toolsets"], "deleted_toolsets": payload.get("deleted_toolsets", [])}


def module_tools(module_name: str) -> list[ToolEntry]:
    """Keep the existing module export order (alphabetical declaration attributes)."""
    module = load_tool_module(module_name)
    result = []
    for attr in dir(module):
        if not attr.endswith("_declaration"):
            continue
        declaration = getattr(module, attr)
        if not isinstance(declaration, dict):
            continue
        function = declaration.get("function", declaration)
        name = function.get("name") if isinstance(function, dict) else None
        if not name:
            continue
        callback = getattr(module, name, None)
        if not callable(callback):
            raise ToolLoadError(f"Tool declaration {module_name}.{attr} references missing or non-callable function {name!r}.")
        result.append((declaration, callback))
    return result


def resolve_reference(reference: str) -> ToolEntry:
    module_name, name = split_reference(reference)
    for declaration, callback in module_tools(module_name):
        if declaration.get("function", declaration).get("name") == name:
            return declaration, callback
    raise ToolLoadError(f"Unknown tool reference: {reference}")


def resolve_toolset(name: str) -> list[ToolEntry]:
    config = load_toolset_config()
    if name in config["deleted_toolsets"]:
        raise ToolLoadError(f"Toolset {name!r} has been deleted. Update the node's tool selection.")
    definition = config["toolsets"].get(name)
    if definition is None:
        return module_tools(name)
    return [resolve_reference(reference) for reference in definition["tools"]]


def build_catalog() -> dict:
    """Discover exports, ignoring implementation modules without tool callables."""
    modules = {}
    exports = {}
    functions_dir = get_functions_dir()
    if not functions_dir:
        raise ToolLoadError("Tool catalog cannot be built: functions directory not found.")
    for path in sorted(Path(functions_dir).glob("*.py")):
        if path.stem.startswith("_"):
            continue
        module = load_tool_module(path.stem)
        # Some implementation files own a declaration but not its callable.
        if not any(attr.endswith("_declaration") and callable(getattr(module, attr[:-12], None))
                   for attr in dir(module)):
            continue
        entries = module_tools(path.stem)
        if not entries:
            continue
        modules[path.stem] = entries
        for declaration, callback in entries:
            name = declaration.get("function", declaration)["name"]
            key = (name, callback)
            reference = f"{path.stem}:{name}"
            preferred = callback.__module__ == f"functions.{path.stem}"
            if key in exports and exports[key][1] != declaration:
                raise ToolLoadError(f"Conflicting declarations for tool {name}.")
            if key not in exports or preferred:
                exports[key] = (reference, declaration)
    defaults = {}
    for name, entries in modules.items():
        defaults[name] = {
            "description": "",
            "tools": [exports[(d.get("function", d)["name"], f)][0] for d, f in entries],
        }
    catalog = []
    for (name, _), (reference, declaration) in exports.items():
        catalog.append({"id": reference, "name": name,
                        "description": declaration.get("function", declaration).get("description", ""),
                        "module": reference.split(":")[0]})
    return {"defaults": defaults, "tools": sorted(catalog, key=lambda item: (item["name"], item["id"]))}


def settings_document() -> dict:
    catalog = build_catalog()
    config = load_toolset_config()
    sets = {**catalog["defaults"], **config["toolsets"]}
    for name in config["deleted_toolsets"]:
        sets.pop(name, None)
    return {"toolsets": sets, "deleted_toolsets": config["deleted_toolsets"]}


def validate_toolsets(payload: object) -> None:
    for name, definition in validate_structure(payload)["toolsets"].items():
        seen = set()
        for reference in definition["tools"]:
            declaration, _ = resolve_reference(reference)
            function_name = declaration.get("function", declaration)["name"]
            if function_name in seen:
                raise ValueError(f"Toolset {name} has multiple entries named {function_name}.")
            seen.add(function_name)
