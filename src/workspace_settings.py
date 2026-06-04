import json
import os
import socket
import sys


DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 8766
DEFAULT_STARTUP_GRAPH_ID = "default"


def get_workspace_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_workspace_config_path() -> str:
    return os.path.join(get_workspace_root(), "config", "config.json")


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
    payload = load_workspace_settings()
    graph_id = str(payload.get("startup_graph_id") or "").strip() or DEFAULT_STARTUP_GRAPH_ID
    graph_name = str(payload.get("startup_graph_name") or "").strip() or graph_id
    return {"graph_id": graph_id, "graph_name": graph_name}
