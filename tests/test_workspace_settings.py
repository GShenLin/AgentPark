import json
import socket
from types import SimpleNamespace

import pytest


def test_read_server_settings_from_workspace_config(monkeypatch, tmp_path):
    from src import workspace_settings

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "server": {
                    "host": "127.0.0.1",
                    "port": 9001,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_server_settings() == {
        "host": "127.0.0.1",
        "port": 9001,
    }


def test_read_server_settings_defaults_to_lan_bind_host(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_server_settings() == {
        "host": "0.0.0.0",
        "port": workspace_settings.DEFAULT_SERVER_PORT,
    }


def test_read_storage_settings_accepts_absolute_memories_path(monkeypatch, tmp_path):
    from src import workspace_settings

    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    memories_root = tmp_path / "runtime-data" / "memories"
    (cache_dir / "memoryLocalConfig.json").write_text(
        json.dumps({"memoriesPath": str(memories_root)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_storage_settings() == {
        "memories_path": str(memories_root),
        "memories_root": str(memories_root),
    }


def test_read_storage_settings_defaults_to_workspace_memories(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_storage_settings()["memories_root"] == str(tmp_path / "memories")


def test_relative_memories_path_falls_back_to_workspace_memories(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.resolve_memories_root(
        {"memoriesPath": "runtime-data/memories"}
    ) == str(tmp_path / "memories")


def test_workspace_root_memories_path_falls_back_to_workspace_memories(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.resolve_memories_root(
        {"memoriesPath": str(tmp_path)}
    ) == str(tmp_path / "memories")


def test_filesystem_root_memories_path_falls_back_to_workspace_memories(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.resolve_memories_root(
        {"memoriesPath": tmp_path.anchor}
    ) == str(tmp_path / "memories")


def test_save_memory_local_config_writes_cache_file(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    memories_root = tmp_path / "external" / "memories"

    workspace_settings.save_memory_local_config({"memoriesPath": str(memories_root)})

    saved = json.loads((tmp_path / ".cache" / "memoryLocalConfig.json").read_text(encoding="utf-8"))
    assert saved == {"memoriesPath": str(memories_root)}


def test_read_storage_settings_does_not_read_legacy_workspace_storage(monkeypatch, tmp_path):
    from src import workspace_settings

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps({"storage": {"memoriesPath": str(tmp_path / "legacy")}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_storage_settings()["memories_root"] == str(tmp_path / "memories")


def test_read_storage_settings_rejects_nonstring_local_path(monkeypatch, tmp_path):
    from src import workspace_settings

    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    (cache_dir / "memoryLocalConfig.json").write_text(
        json.dumps({"memoriesPath": 42}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    with pytest.raises(ValueError, match="memoriesPath.*string"):
        workspace_settings.read_storage_settings()


def test_unusable_absolute_memories_path_falls_back_at_runtime(monkeypatch, tmp_path):
    from src import memory_root, workspace_settings

    blocked_path = tmp_path / "blocked"
    blocked_path.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(memory_root, "_active_memories_root", "")

    assert memory_root.configure_memories_root(str(blocked_path)) == str(tmp_path / "memories")
    assert (tmp_path / "memories").is_dir()


def test_read_undo_settings_defaults_to_five(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_undo_settings() == {"max_steps": 5}


def test_resolve_local_client_host_maps_wildcard_to_loopback():
    from src import workspace_settings

    assert workspace_settings.resolve_local_client_host("0.0.0.0") == "127.0.0.1"
    assert workspace_settings.resolve_local_client_host("::") == "127.0.0.1"
    assert workspace_settings.resolve_local_client_host("10.231.113.79") == "10.231.113.79"


def test_fast_api_main_uses_workspace_server_defaults(monkeypatch):
    import src.fast_api as fast_api

    captured = {}
    fake_app = object()

    monkeypatch.setattr(fast_api, "read_server_settings", lambda: {"host": "127.0.0.1", "port": 9101})
    monkeypatch.setattr(
        fast_api,
        "read_storage_settings",
        lambda: {"memories_path": "data/memories", "memories_root": "C:/data/memories"},
    )
    monkeypatch.setattr(
        fast_api.runtime_paths,
        "configure_graphs_dir",
        lambda path: captured.update({"memories_root": path}) or path,
    )
    monkeypatch.setattr(fast_api, "find_available_server_port", lambda host, port: 9103)
    monkeypatch.setattr(fast_api, "install_server_pid_file", lambda host, port: captured.update({"pid_host": host, "pid_port": port}) or "pid-file")
    monkeypatch.setattr(fast_api, "create_app", lambda: fake_app)
    monkeypatch.setattr(
        fast_api,
        "_run_server",
        lambda app, host, port, log_config: captured.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "log_config": log_config,
            }
        ),
    )

    fast_api.main(["--no-browser"])

    assert captured["app"] is fake_app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9103
    assert captured["pid_host"] == "127.0.0.1"
    assert captured["pid_port"] == 9103
    assert captured["memories_root"] == "C:/data/memories"


def test_find_available_server_port_skips_occupied_port():
    from src import workspace_settings

    first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    first.bind(("127.0.0.1", 0))
    occupied_port = first.getsockname()[1]

    second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    second.bind(("127.0.0.1", 0))
    blocked_next_port = second.getsockname()[1]

    try:
        start_port = min(occupied_port, blocked_next_port)
        expected = start_port
        while expected in {occupied_port, blocked_next_port}:
            expected += 1

        resolved = workspace_settings.find_available_server_port("127.0.0.1", start_port, max_attempts=10)

        assert resolved == expected
    finally:
        first.close()
        second.close()


def test_read_startup_graph_settings_uses_local_cache(monkeypatch, tmp_path):
    from src import workspace_settings

    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    (cache_dir / "startup_graph.json").write_text(
        json.dumps(
            {
                "graph_id": "graph-b",
                "graph_name": "Graph B",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_startup_graph_settings() == {
        "graph_id": "graph-b",
        "graph_name": "Graph B",
    }


def test_read_startup_graph_settings_defaults_when_cache_missing(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    assert workspace_settings.read_startup_graph_settings() == {
        "graph_id": "default",
        "graph_name": "default",
    }


def test_graph_api_updates_startup_graph_cache_without_overwriting_server_settings(monkeypatch, tmp_path):
    import src.workspace_settings as workspace_settings
    from src.web_backend.core_graph_api import GraphApiDomain

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "server": {
                    "host": "127.0.0.1",
                    "port": 9301,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    graph_runtime = SimpleNamespace(_sanitize_graph_id=lambda value: str(value).strip())
    core = SimpleNamespace(default_graph_id="default", graph_runtime=graph_runtime)
    domain = GraphApiDomain(core, graph_runtime)

    result = domain.set_startup_graph_config({"graph_id": "graph-b", "graph_name": "Graph B"})

    assert result == {"ok": True, "graph_id": "graph-b", "graph_name": "Graph B"}

    saved = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert saved == {
        "server": {
            "host": "127.0.0.1",
            "port": 9301,
        }
    }
    startup = json.loads((tmp_path / ".cache" / "startup_graph.json").read_text(encoding="utf-8"))
    assert startup == {
        "graph_id": "graph-b",
        "graph_name": "Graph B",
    }
