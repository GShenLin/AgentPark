import os
import sys

from ..memory_root import configure_memories_root, get_memories_root
from ..workspace_settings import get_workspace_root


def _get_runtime_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return get_workspace_root()


def _get_resource_root() -> str:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
    return _get_runtime_root()


def _get_functions_dir() -> str:
    runtime_root = _get_runtime_root()
    candidate = os.path.join(runtime_root, "functions")
    if os.path.isdir(candidate):
        return candidate
    resource_root = _get_resource_root()
    candidate = os.path.join(resource_root, "functions")
    if os.path.isdir(candidate):
        return candidate
    return ""


def _get_nodes_dir() -> str:
    runtime_root = _get_runtime_root()
    candidate = os.path.join(runtime_root, "nodes")
    if os.path.isdir(candidate):
        return candidate
    resource_root = _get_resource_root()
    candidate = os.path.join(resource_root, "nodes")
    if os.path.isdir(candidate):
        return candidate
    return ""


def _get_graphs_dir() -> str:
    return get_memories_root()


def configure_graphs_dir(path: str) -> str:
    return configure_memories_root(path)
