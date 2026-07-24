import json
import os
import socket
import sys


DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 8766
DEFAULT_STARTUP_GRAPH_ID = "default"
DEFAULT_MAX_UNDO_STEPS = 5
STARTUP_GRAPH_CACHE_FILENAME = "startup_graph.json"
MEMORY_LOCAL_CONFIG_FILENAME = "memoryLocalConfig.json"


def get_workspace_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_workspace_config_path() -> str:
    return os.path.join(get_workspace_root(), "config", "config.json")


def get_workspace_cache_dir() -> str:
    return os.path.join(get_workspace_root(), ".cache")


def get_startup_graph_cache_path() -> str:
    return os.path.join(get_workspace_cache_dir(), STARTUP_GRAPH_CACHE_FILENAME)


def get_memory_local_config_path() -> str:
    return os.path.join(get_workspace_cache_dir(), MEMORY_LOCAL_CONFIG_FILENAME)


def load_workspace_settings() -> dict:
    path = get_workspace_config_path()
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("config/config.json must contain a top-level object.")
    return payload


def save_workspace_settings(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("workspace settings must be an object.")
    path = get_workspace_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def validate_memory_local_config(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(".cache/memoryLocalConfig.json must contain a top-level object.")
    memories_path = payload.get("memoriesPath")
    if memories_path is not None and not isinstance(memories_path, str):
        raise ValueError(".cache/memoryLocalConfig.json field 'memoriesPath' must be a string.")
    return payload


def load_memory_local_config() -> dict:
    path = get_memory_local_config_path()
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return validate_memory_local_config(payload)


def save_memory_local_config(payload: dict) -> None:
    validated = validate_memory_local_config(payload)
    path = get_memory_local_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(validated, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def load_startup_graph_cache() -> dict:
    path = get_startup_graph_cache_path()
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(".cache/startup_graph.json must contain a top-level object.")
    return payload


def save_startup_graph_settings(graph_id: str, graph_name: str) -> None:
    safe_graph_id = str(graph_id or "").strip()
    if not safe_graph_id:
        raise ValueError("startup graph_id is required.")
    safe_graph_name = str(graph_name or "").strip() or safe_graph_id
    path = get_startup_graph_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "graph_id": safe_graph_id,
        "graph_name": safe_graph_name,
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def read_server_settings() -> dict:
    payload = load_workspace_settings()
    server = payload.get("server")
    if server is None:
        server = {}
    if not isinstance(server, dict):
        raise ValueError("config/config.json field 'server' must be an object.")

    host = str(server.get("host") or "").strip() or DEFAULT_SERVER_HOST
    port_value = server.get("port", DEFAULT_SERVER_PORT)
    try:
        port = int(port_value)
    except Exception as exc:
        raise ValueError("config/config.json field 'server.port' must be an integer.") from exc
    if port <= 0 or port > 65535:
        raise ValueError("config/config.json field 'server.port' must be between 1 and 65535.")

    return {"host": host, "port": port}


def read_undo_settings() -> dict:
    payload = load_workspace_settings()
    undo = payload.get("undo")
    if undo is None:
        undo = {}
    if not isinstance(undo, dict):
        raise ValueError("config/config.json field 'undo' must be an object.")
    value = undo.get("maxSteps", DEFAULT_MAX_UNDO_STEPS)
    if isinstance(value, bool):
        raise ValueError("config/config.json field 'undo.maxSteps' must be an integer.")
    try:
        max_steps = int(value)
    except Exception as exc:
        raise ValueError("config/config.json field 'undo.maxSteps' must be an integer.") from exc
    if max_steps < 0 or max_steps > 100:
        raise ValueError("config/config.json field 'undo.maxSteps' must be between 0 and 100.")
    return {"max_steps": max_steps}


def resolve_memories_root(payload: dict | None = None) -> str:
    local_config = load_memory_local_config() if payload is None else validate_memory_local_config(payload)
    workspace_root = os.path.abspath(get_workspace_root())
    fallback_root = os.path.join(workspace_root, "memories")
    configured_path = local_config.get("memoriesPath")
    if configured_path is None:
        return fallback_root
    path_text = configured_path.strip()
    if not path_text:
        return fallback_root
    expanded_path = os.path.expanduser(os.path.expandvars(path_text))
    if not os.path.isabs(expanded_path):
        return fallback_root
    resolved_path = os.path.abspath(expanded_path)
    if (
        os.path.normcase(resolved_path) == os.path.normcase(workspace_root)
        or os.path.dirname(resolved_path) == resolved_path
    ):
        return fallback_root
    return resolved_path


def read_storage_settings() -> dict:
    resolved_root = resolve_memories_root()
    return {
        "memories_path": resolved_root,
        "memories_root": resolved_root,
    }


def resolve_local_client_host(bind_host: str) -> str:
    host_text = str(bind_host or "").strip() or DEFAULT_SERVER_HOST
    if host_text in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host_text


def _build_bind_probe_targets(host: str, port: int) -> list[tuple[int, tuple]]:
    host_text = str(host or "").strip() or DEFAULT_SERVER_HOST
    if host_text == "::":
        return [(socket.AF_INET6, ("::", int(port), 0, 0))]
    if host_text in {"0.0.0.0", ""}:
        return [(socket.AF_INET, ("0.0.0.0", int(port)))]

    targets: list[tuple[int, tuple]] = []
    try:
        infos = socket.getaddrinfo(host_text, int(port), type=socket.SOCK_STREAM)
    except socket.gaierror:
        infos = []
    for family, socktype, proto, canonname, sockaddr in infos:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        if socktype != socket.SOCK_STREAM:
            continue
        targets.append((family, sockaddr))
    if targets:
        return targets
    return [(socket.AF_INET, (host_text, int(port)))]


def is_server_port_available(host: str, port: int) -> bool:
    targets = _build_bind_probe_targets(host, port)
    for family, sockaddr in targets:
        probe = None
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
            if family == socket.AF_INET6 and hasattr(socket, "IPPROTO_IPV6") and hasattr(socket, "IPV6_V6ONLY"):
                try:
                    probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                except OSError:
                    pass
            probe.bind(sockaddr)
        except OSError:
            return False
        finally:
            if probe is not None:
                try:
                    probe.close()
                except OSError:
                    pass
    return True


def find_available_server_port(host: str, preferred_port: int, max_attempts: int = 100) -> int:
    try:
        port = int(preferred_port)
    except Exception as exc:
        raise ValueError("preferred_port must be an integer.") from exc
    if port <= 0 or port > 65535:
        raise ValueError("preferred_port must be between 1 and 65535.")

    attempts = max(1, int(max_attempts))
    candidate = port
    for _ in range(attempts):
        if is_server_port_available(host, candidate):
            return candidate
        candidate += 1
        if candidate > 65535:
            break
    raise RuntimeError(
        f"failed to find an available port for host={host!r} starting from port={port} within {attempts} attempts"
    )


def read_startup_graph_settings() -> dict:
    payload = load_startup_graph_cache()
    graph_id = str(payload.get("graph_id") or "").strip() or DEFAULT_STARTUP_GRAPH_ID
    graph_name = str(payload.get("graph_name") or "").strip() or graph_id
    return {"graph_id": graph_id, "graph_name": graph_name}
