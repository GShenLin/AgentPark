import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.web_backend import core_system_api
from src import fast_api


@pytest.mark.skipif(os.name == "nt", reason="POSIX restart launcher")
def test_restart_detaches_and_preserves_listener(monkeypatch, tmp_path):
    (tmp_path / "Restart.sh").touch()
    monkeypatch.setattr(core_system_api, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setenv("AGENTPARK_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("AGENTPARK_SERVER_PORT", "8789")
    launch = Mock()
    monkeypatch.setattr(core_system_api.subprocess, "Popen", launch)
    api = core_system_api.SystemApiDomain(object())
    result = api.restart_server()
    assert result["instance_id"] == api.server_status()["instance_id"]
    args, kwargs = launch.call_args
    assert args[0] == [str(tmp_path / "Restart.sh"), "server"]
    assert kwargs["env"]["AGENTPARK_RESTART_LISTENER"] == "1"
    assert kwargs["env"]["AGENTPARK_SERVER_PORT"] == "8789"
    assert kwargs["start_new_session"]
    assert kwargs["stdin"] == core_system_api.subprocess.DEVNULL
    assert kwargs["stdout"].name == str(tmp_path / ".runtime" / "restart.log")


def test_restarted_server_keeps_actual_listener(monkeypatch):
    monkeypatch.setenv("AGENTPARK_RESTART_LISTENER", "1")
    monkeypatch.setenv("AGENTPARK_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("AGENTPARK_SERVER_PORT", "8789")
    monkeypatch.setattr(fast_api, "apply_project_process_environment", lambda: None)
    monkeypatch.setattr(fast_api, "read_server_settings", lambda: {"host": "127.0.0.1", "port": 8788})
    find_port = Mock(side_effect=AssertionError("restart must not select another port"))
    monkeypatch.setattr(fast_api, "find_available_server_port", find_port)
    monkeypatch.setattr(fast_api, "read_storage_settings", lambda: {"memories_root": "/unused"})
    monkeypatch.setattr(fast_api.runtime_paths, "configure_graphs_dir", lambda _: None)
    monkeypatch.setattr(fast_api, "install_server_pid_file", Mock(return_value="pid"))
    monkeypatch.setattr(fast_api, "create_app", lambda: SimpleNamespace())
    run = Mock()
    monkeypatch.setattr(fast_api, "_run_server", run)
    fast_api.main([])
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["port"] == 8789
    find_port.assert_not_called()
