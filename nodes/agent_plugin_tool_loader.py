from __future__ import annotations

import hashlib
import importlib.util
import copy
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable

from src.tool.base_tool import BaseTool
from src.tool.tool_load_errors import ToolLoadError


@dataclass(frozen=True)
class PluginToolDefinition:
    name: str
    source_name: str
    path: str
    declaration: dict
    callable: object


class PluginToolLoadError(RuntimeError):
    pass


def load_plugin_tool_path(plugin_dir: str, reference: str) -> list[PluginToolDefinition]:
    text = str(reference or "").strip()
    if not text.startswith("./") and not text.startswith(".\\"):
        return []
    base = os.path.realpath(plugin_dir)
    path = os.path.realpath(os.path.join(base, text))
    if not _is_inside(base, path):
        raise PluginToolLoadError(f"plugin tool path escapes plugin root: {text}")
    if os.path.isfile(path):
        if not path.endswith(".py"):
            raise PluginToolLoadError(f"plugin tool file must be a Python module: {path}")
        return _load_tool_module_file(path)
    if not os.path.isdir(path):
        raise PluginToolLoadError(f"plugin tool path does not exist: {path}")

    definitions: list[PluginToolDefinition] = []
    for current_dir, dirnames, filenames in os.walk(path):
        dirnames[:] = [name for name in dirnames if _is_valid_path_part(name) and not name.startswith(".")]
        for filename in sorted(filenames):
            if not filename.endswith(".py") or filename == "__init__.py":
                continue
            definitions.extend(_load_tool_module_file(os.path.join(current_dir, filename)))
    if not definitions:
        raise PluginToolLoadError(f"plugin tool path contains no tool declarations: {path}")
    return definitions


def dedupe_plugin_tool_definitions(tools: Iterable[PluginToolDefinition]) -> list[PluginToolDefinition]:
    result: list[PluginToolDefinition] = []
    seen: set[str] = set()
    for tool in tools or []:
        key = str(tool.name or "").casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tool)
    return result


def materialize_plugin_tool_definitions(
    plugin_id: str,
    tools: Iterable[PluginToolDefinition],
) -> list[PluginToolDefinition]:
    plugin_part = _safe_function_part(plugin_id, "plugin id")
    result: list[PluginToolDefinition] = []
    for tool in tools or []:
        source_name = str(tool.source_name or tool.name or "").strip()
        tool_part = _safe_function_part(source_name, "plugin tool name")
        function_name = f"plugin__{plugin_part}__{tool_part}"
        result.append(
            PluginToolDefinition(
                name=function_name,
                source_name=source_name,
                path=tool.path,
                declaration=_with_function_name(tool.declaration, function_name),
                callable=tool.callable,
            )
        )
    return dedupe_plugin_tool_definitions(result)


def register_plugin_tool_definitions(agent: object, tools: Iterable[PluginToolDefinition]) -> None:
    register = getattr(getattr(agent, "tools", None), "register_external_tool", None)
    if not callable(register):
        raise PluginToolLoadError("agent does not support plugin tool registration")
    for tool in tools or []:
        register(tool.declaration, tool.callable)


def _load_tool_module_file(path: str) -> list[PluginToolDefinition]:
    module = _import_module_file(path)
    definitions: list[PluginToolDefinition] = []
    for attr_name in dir(module):
        if not attr_name.endswith("_declaration"):
            continue
        declaration = getattr(module, attr_name)
        if not isinstance(declaration, dict):
            continue
        func_name = _extract_function_name(declaration)
        try:
            BaseTool._validate_tool_function_name(func_name, path, attr_name)
        except ValueError as exc:
            raise PluginToolLoadError(str(exc)) from exc
        if not hasattr(module, func_name):
            raise PluginToolLoadError(
                f"Tool declaration {path}.{attr_name} references missing function {func_name!r}."
            )
        func = getattr(module, func_name)
        if not callable(func):
            raise PluginToolLoadError(
                f"Tool declaration {path}.{attr_name} points to non-callable function {func_name!r}."
            )
        definitions.append(
            PluginToolDefinition(
                name=func_name,
                source_name=func_name,
                path=path,
                declaration=dict(declaration),
                callable=func,
            )
        )
    if not definitions:
        raise PluginToolLoadError(f"plugin tool module contains no declarations: {path}")
    return definitions


def _import_module_file(path: str):
    module_name = "_agentpark_plugin_tool_" + hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise PluginToolLoadError(f"failed to load plugin tool module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except ToolLoadError:
        raise
    except Exception as exc:
        raise PluginToolLoadError(f"failed to execute plugin tool module {path}: {type(exc).__name__}: {exc}") from exc
    return module


def _extract_function_name(declaration: dict) -> str:
    function = declaration.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "").strip()
    return str(declaration.get("name") or "").strip()


def _with_function_name(declaration: dict, function_name: str) -> dict:
    result = copy.deepcopy(declaration)
    function = result.get("function")
    if isinstance(function, dict):
        function["name"] = function_name
    else:
        result["name"] = function_name
    return result


def _safe_function_part(value: str, label: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise PluginToolLoadError(f"{label} cannot be converted to a provider-safe function name")
    return text


def _is_inside(root: str, candidate: str) -> bool:
    return os.path.commonpath([os.path.realpath(root), os.path.realpath(candidate)]) == os.path.realpath(root)


def _is_valid_path_part(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(value or "")))
