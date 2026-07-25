from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class NodeModuleSource:
    type_id: str
    file_path: str
    is_package: bool


def resolve_node_module(nodes_dir: str, type_id: str) -> NodeModuleSource | None:
    safe_nodes_dir = os.path.abspath(str(nodes_dir or ""))
    safe_type_id = str(type_id or "").strip()
    if not safe_nodes_dir or not safe_type_id:
        return None
    file_path = os.path.join(safe_nodes_dir, f"{safe_type_id}.py")
    package_path = os.path.join(safe_nodes_dir, safe_type_id, "__init__.py")
    has_file = os.path.isfile(file_path)
    has_package = os.path.isfile(package_path)
    if has_file and has_package:
        raise RuntimeError(
            f"Node type {safe_type_id!r} is ambiguous: both a module file and package exist."
        )
    if has_package:
        return NodeModuleSource(
            type_id=safe_type_id,
            file_path=package_path,
            is_package=True,
        )
    if has_file:
        return NodeModuleSource(
            type_id=safe_type_id,
            file_path=file_path,
            is_package=False,
        )
    return None


def iter_node_modules(nodes_dir: str) -> list[NodeModuleSource]:
    safe_nodes_dir = os.path.abspath(str(nodes_dir or ""))
    if not os.path.isdir(safe_nodes_dir):
        return []
    type_ids: set[str] = set()
    for name in os.listdir(safe_nodes_dir):
        path = os.path.join(safe_nodes_dir, name)
        if os.path.isfile(path) and name.endswith(".py"):
            type_id = name[:-3]
            if type_id not in {"__init__", "base_node"}:
                type_ids.add(type_id)
        elif os.path.isdir(path) and os.path.isfile(os.path.join(path, "__init__.py")):
            type_ids.add(name)
    sources: list[NodeModuleSource] = []
    for type_id in sorted(type_ids):
        source = resolve_node_module(safe_nodes_dir, type_id)
        if source is not None:
            sources.append(source)
    return sources


def module_spec_kwargs(file_path: str, *, is_package: bool) -> dict[str, object]:
    if not is_package:
        return {}
    return {"submodule_search_locations": [os.path.dirname(file_path)]}


__all__ = [
    "NodeModuleSource",
    "iter_node_modules",
    "module_spec_kwargs",
    "resolve_node_module",
]
