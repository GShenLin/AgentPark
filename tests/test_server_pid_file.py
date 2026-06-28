import json
import os


def test_write_server_pid_file_records_runtime_contract(tmp_path):
    from src import server_pid_file

    pid_path = server_pid_file.write_server_pid_file("127.0.0.1", 9107, workspace_root=str(tmp_path))

    assert pid_path == os.path.join(str(tmp_path), ".runtime", "aitools-server.pid")
    payload = json.loads((tmp_path / ".runtime" / "aitools-server.pid").read_text(encoding="utf-8"))

    assert payload["schema_version"] == server_pid_file.PID_FILE_SCHEMA_VERSION
    assert payload["app"] == "AITools"
    assert payload["kind"] == "fast_api_server"
    assert payload["pid"] == os.getpid()
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 9107
    assert payload["workspace_root"] == str(tmp_path)


def test_remove_server_pid_file_preserves_newer_owner(tmp_path):
    from src import server_pid_file

    pid_path = server_pid_file.write_server_pid_file("127.0.0.1", 9108, workspace_root=str(tmp_path))

    server_pid_file.remove_server_pid_file(pid_path, expected_pid=os.getpid() + 1)
    assert os.path.exists(pid_path)

    server_pid_file.remove_server_pid_file(pid_path, expected_pid=os.getpid())
    assert not os.path.exists(pid_path)
