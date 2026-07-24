import os

from .node_memory_paths import MEMORY_FILENAME, MESSAGES_FILENAME


NODE_CONFIG_PATH_CONTEXT_KEY = "node_config_path"


def bind_node_storage_context(context: dict, config_path: str) -> dict:
    """Bind one node execution to the storage location selected by the graph runtime."""
    if not isinstance(context, dict):
        raise TypeError("node execution context must be a dictionary")
    raw_config_path = str(config_path or "").strip()
    if not raw_config_path:
        raise ValueError("node config path is required")

    resolved_config_path = os.path.abspath(raw_config_path)
    paths = resolve_node_storage_paths(resolved_config_path)
    context[NODE_CONFIG_PATH_CONTEXT_KEY] = resolved_config_path
    context["memory_path"] = paths["memory_path"]
    context["messages_path"] = paths["messages_path"]
    return context


def resolve_node_storage_paths(config_path: str) -> dict[str, str]:
    resolved_config_path = os.path.abspath(str(config_path or "").strip())
    node_directory = os.path.dirname(resolved_config_path)
    return {
        "memory_path": os.path.join(node_directory, MEMORY_FILENAME),
        "messages_path": os.path.join(node_directory, MESSAGES_FILENAME),
    }
