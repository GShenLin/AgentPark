from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import threading
import uuid
from copy import deepcopy
from collections.abc import Callable

from . import runtime_paths
from .route_parser import NodeRouteParser


class NodeMetadataError(RuntimeError):
    pass


class NodeModuleLoadError(NodeMetadataError):
    pass


class NodeMetadataReadError(NodeMetadataError):
    pass


class NodeCreateError(NodeMetadataError):
    pass


class NodeMetadataSignatureError(NodeMetadataError):
    pass


_NODE_CLASS_CACHE: dict[str, tuple[tuple[int, int], type]] = {}
_NODE_CLASS_CACHE_LOCK = threading.RLock()


def _node_source_version(file_path: str) -> tuple[int, int]:
    stat = os.stat(file_path)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _load_node_class(file_path: str, safe_type_id: str) -> type | None:
    normalized_path = os.path.normcase(os.path.abspath(file_path))
    try:
        source_version = _node_source_version(normalized_path)
    except OSError as exc:
        raise NodeModuleLoadError(
            f"Cannot inspect node module {safe_type_id!r}: {type(exc).__name__}: {exc}"
        ) from exc

    with _NODE_CLASS_CACHE_LOCK:
        cached = _NODE_CLASS_CACHE.get(normalized_path)
        if cached is not None and cached[0] == source_version:
            return cached[1]

        module_name = f"nodes_init_{safe_type_id}_{uuid.uuid4().hex}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, normalized_path)
            if not spec or not spec.loader:
                raise NodeModuleLoadError(f"Cannot build import spec for node {safe_type_id!r}.")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            node_cls = getattr(module, "Node", None)
            if node_cls is None:
                _NODE_CLASS_CACHE.pop(normalized_path, None)
                return None
            if not isinstance(node_cls, type):
                raise NodeModuleLoadError(f"Node export in {safe_type_id!r} must be a class.")
            _NODE_CLASS_CACHE[normalized_path] = (source_version, node_cls)
            return node_cls
        except NodeModuleLoadError:
            raise
        except Exception as exc:
            raise NodeModuleLoadError(
                f"Error loading node module {safe_type_id!r}: {type(exc).__name__}: {exc}"
            ) from exc


def load_node_instance(type_id: str):
    safe_type_id = str(type_id or "").strip()
    if not safe_type_id:
        return None
    nodes_dir = runtime_paths._get_nodes_dir()
    if not nodes_dir or not os.path.isdir(nodes_dir):
        return None
    file_path = os.path.join(nodes_dir, f"{safe_type_id}.py")
    if not os.path.exists(file_path):
        return None

    runtime_root = runtime_paths._get_runtime_root()
    if runtime_root and runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    resource_root = runtime_paths._get_resource_root()
    if resource_root and resource_root not in sys.path:
        sys.path.insert(0, resource_root)

    try:
        node_cls = _load_node_class(file_path, safe_type_id)
        if node_cls is None:
            return None
        return node_cls()
    except NodeModuleLoadError:
        raise
    except Exception as exc:
        raise NodeModuleLoadError(f"Error loading node module {safe_type_id!r}: {type(exc).__name__}: {exc}") from exc


def read_node_ports(node: object, context: dict | None = None) -> tuple[int, int]:
    if node is None:
        return (1, 1)
    return (_read_port(node, "getInputNum", context), _read_port(node, "getOutputNum", context))


def read_node_schema(node: object, context: dict | None = None) -> dict[str, dict]:
    if node is None:
        return {}
    get_schema = getattr(node, "get_config_schema", None)
    if callable(get_schema):
        try:
            schema = _call_optional_context(get_schema, context, "get_config_schema")
        except NodeMetadataSignatureError:
            raise
        except Exception as exc:
            raise NodeMetadataReadError(f"Error reading node schema: {type(exc).__name__}: {exc}") from exc
    else:
        schema = getattr(node, "config_schema", None)
    if not isinstance(schema, dict):
        return {}
    output: dict[str, dict] = {}
    for key, value in schema.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, dict):
            continue
        output[key] = deepcopy(value)
    return output


def read_node_internal_fields(node: object, context: dict | None = None) -> set[str]:
    if node is None:
        return set()
    getter = getattr(node, "get_internal_config_fields", None)
    if callable(getter):
        try:
            fields = _call_optional_context(getter, context, "get_internal_config_fields")
        except NodeMetadataSignatureError:
            raise
        except Exception as exc:
            raise NodeMetadataReadError(f"Error reading node internal fields: {type(exc).__name__}: {exc}") from exc
    else:
        fields = getattr(node, "internal_config_fields", None)
    if not isinstance(fields, set):
        return set()
    return {str(item).strip() for item in fields if str(item).strip()}


def run_node_on_create(node: object, config: dict, context: dict) -> None:
    if node is None:
        return
    on_create = getattr(node, "on_create", None)
    if not callable(on_create):
        return
    try:
        _call_on_create(on_create, config, context)
    except NodeMetadataSignatureError:
        raise
    except Exception as exc:
        raise NodeCreateError(f"Error running node on_create: {type(exc).__name__}: {exc}") from exc


def _read_port(node: object, method_name: str, context: dict | None) -> int:
    getter = getattr(node, method_name, None)
    if not callable(getter):
        return 1
    try:
        return NodeRouteParser.parse_port_count(_call_optional_context(getter, context, method_name), default=1)
    except NodeMetadataSignatureError:
        raise
    except Exception as exc:
        raise NodeMetadataReadError(f"Error reading {method_name}: {type(exc).__name__}: {exc}") from exc


def _call_optional_context(fn: Callable, context: dict | None, label: str):
    required, maximum = _callable_positional_range(fn, label)
    if required == 0 and maximum == 0:
        return fn()
    if required <= 1 and maximum == 1:
        return fn(context)
    raise NodeMetadataSignatureError(f"{label} must accept zero arguments or one context argument.")


def _call_on_create(fn: Callable, config: dict, context: dict):
    required, maximum = _callable_positional_range(fn, "on_create")
    if required <= 2 and maximum == 2:
        return fn(config, context)
    if required <= 1 and maximum == 1:
        return fn(config)
    raise NodeMetadataSignatureError("on_create must accept config or config plus context.")


def _callable_positional_range(fn: Callable, label: str) -> tuple[int, int]:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise NodeMetadataSignatureError(f"Cannot inspect {label} signature: {type(exc).__name__}: {exc}") from exc
    required = 0
    maximum = 0
    has_varargs = False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            has_varargs = True
            continue
        if parameter.kind not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            continue
        maximum += 1
        if parameter.default is inspect.Parameter.empty:
            required += 1
    if has_varargs:
        maximum = 1_000_000
    return required, maximum
