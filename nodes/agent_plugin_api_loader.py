from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from typing import Any

from nodes.agent_plugin_manifest import first_manifest_filename, read_plugin_manifest


SUPPORTED_METHODS = frozenset({"delete", "get", "patch", "post", "put"})


@dataclass(frozen=True)
class PluginApiContext:
    plugin_id: str
    plugin_dir: str
    runtime_root: str
    resource_root: str
    core: Any | None = None


@dataclass(frozen=True)
class PluginApiRegistration:
    plugin_id: str
    module_path: str
    method: str
    path: str


class PluginApiLoadError(RuntimeError):
    pass


def register_installed_plugin_apis(
    app: object,
    *,
    plugin_root: str,
    runtime_root: str,
    resource_root: str,
    core: Any | None = None,
) -> list[PluginApiRegistration]:
    root = os.path.realpath(plugin_root)
    if not os.path.isdir(root):
        return []

    registrations: list[PluginApiRegistration] = []
    occupied = _registered_routes(app)
    plugin_ids: set[str] = set()
    for plugin_dir, manifest_path in _iter_manifest_paths(root):
        manifest = read_plugin_manifest(manifest_path)
        if not manifest.server_api:
            continue
        if manifest.id in plugin_ids:
            raise PluginApiLoadError(f"duplicate plugin id with serverApi: {manifest.id}")
        plugin_ids.add(manifest.id)
        context = PluginApiContext(
            plugin_id=manifest.id,
            plugin_dir=plugin_dir,
            runtime_root=os.path.abspath(runtime_root),
            resource_root=os.path.abspath(resource_root),
            core=core,
        )
        for reference in manifest.server_api:
            module_path = _resolve_module_path(plugin_dir, reference)
            module = _import_module(module_path)
            factory = getattr(module, "get_api_routes", None)
            if not callable(factory):
                raise PluginApiLoadError(
                    f"plugin server API module must export get_api_routes(context): {module_path}"
                )
            try:
                route_values = factory(context)
            except Exception as exc:
                raise PluginApiLoadError(
                    f"plugin server API factory failed for {manifest.id}: {type(exc).__name__}: {exc}"
                ) from exc
            if not isinstance(route_values, (list, tuple)) or not route_values:
                raise PluginApiLoadError(
                    f"plugin server API factory must return a non-empty route list: {module_path}"
                )
            for index, value in enumerate(route_values):
                method, path, handler, name = _validate_route(value, module_path, index)
                route_key = (method.upper(), path)
                if route_key in occupied:
                    raise PluginApiLoadError(
                        f"plugin server API route conflicts with an existing route: {method.upper()} {path}"
                    )
                occupied.add(route_key)
                add_api_route = getattr(app, "add_api_route", None)
                if not callable(add_api_route):
                    raise PluginApiLoadError("web application does not support add_api_route")
                add_api_route(path, handler, methods=[method.upper()], name=name)
                registrations.append(
                    PluginApiRegistration(
                        plugin_id=manifest.id,
                        module_path=module_path,
                        method=method,
                        path=path,
                    )
                )
    return registrations


def _iter_manifest_paths(root: str):
    for current_dir, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        manifest_name = first_manifest_filename(filenames)
        if not manifest_name:
            continue
        yield current_dir, os.path.join(current_dir, manifest_name)
        dirnames[:] = []


def _resolve_module_path(plugin_dir: str, reference: str) -> str:
    text = str(reference or "").strip()
    if not text.startswith("./") and not text.startswith(".\\"):
        raise PluginApiLoadError(f"plugin serverApi must use a plugin-local path: {text!r}")
    root = os.path.realpath(plugin_dir)
    path = os.path.realpath(os.path.join(root, text))
    if os.path.commonpath([root, path]) != root:
        raise PluginApiLoadError(f"plugin serverApi path escapes plugin root: {text}")
    if not os.path.isfile(path) or not path.endswith(".py"):
        raise PluginApiLoadError(f"plugin serverApi module does not exist or is not Python: {path}")
    return path


def _import_module(path: str):
    module_name = "_agentpark_plugin_api_" + hashlib.sha256(path.encode("utf-8")).hexdigest()
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise PluginApiLoadError(f"failed to load plugin server API module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PluginApiLoadError(
            f"failed to execute plugin server API module {path}: {type(exc).__name__}: {exc}"
        ) from exc
    return module


def _validate_route(value: Any, module_path: str, index: int):
    if not isinstance(value, dict):
        raise PluginApiLoadError(f"plugin API route {module_path}[{index}] must be an object")
    method = str(value.get("method") or "").strip().lower()
    if method not in SUPPORTED_METHODS:
        raise PluginApiLoadError(f"plugin API route has unsupported method: {method!r}")
    path = str(value.get("path") or "").strip()
    if not path.startswith("/api/") or "?" in path or "#" in path:
        raise PluginApiLoadError(f"plugin API route path must start with /api/: {path!r}")
    handler = value.get("handler")
    if not callable(handler):
        raise PluginApiLoadError(f"plugin API route handler is not callable: {method.upper()} {path}")
    name_value = value.get("name")
    name = str(name_value).strip() if name_value is not None else None
    return method, path, handler, name or None


def _registered_routes(app: object) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for route in getattr(app, "routes", []) or []:
        path = str(getattr(route, "path", "") or "")
        for method in getattr(route, "methods", set()) or set():
            result.add((str(method).upper(), path))
    return result


__all__ = [
    "PluginApiContext",
    "PluginApiLoadError",
    "PluginApiRegistration",
    "register_installed_plugin_apis",
]
