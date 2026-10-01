import json
import threading
from pathlib import Path

import pytest

from src.runtime_cancellation import raise_if_cancel_requested
from src.remote_worker.client import JsonHttpTransport, RemoteWorkerClient
from src.remote_worker.identity import IdentityStore, WorkerConfiguration
from src.remote_workspace.operations import WorkspaceOperationRegistry
from src.remote_worker.protocol import ProtocolError, RemoteTask, normalize_server_origin
from src.remote_workspace.capabilities import REMOTE_FILE_SYSTEM_TOOL_NAMES
from src.remote_workspace.capabilities import STANDALONE_REMOTE_CAPABILITIES


def test_linux_state_directory_uses_user_config(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from src.remote_worker import identity

    monkeypatch.setattr(identity, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows-only"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert identity.default_state_directory() == tmp_path / "config" / "AgentParkRemote"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert identity.default_state_directory() == Path.home() / ".config" / "AgentParkRemote"


def _configuration(tmp_path: Path) -> WorkerConfiguration:
    store = IdentityStore(tmp_path / "state" / "identity.json")
    return WorkerConfiguration(store, store.load_or_create())


def test_protocol_parses_task_envelope_strictly():
    task = RemoteTask.from_poll_response(
        {
            "ok": True,
            "task": {
                "task_id": "task-1",
                "tool_name": "read_file",
                "arguments": {"file_path": "README.md"},
                "working_path": r"D:\Projects\Demo",
                "timeout_seconds": 30,
            },
        }
    )

    assert task is not None
    assert task.tool_name == "read_file"
    assert task.arguments == {"file_path": "README.md"}

    with pytest.raises(ProtocolError, match="task.arguments must be a JSON object"):
        RemoteTask.from_poll_response(
            {
                "ok": True,
                "task": {
                    "task_id": "task-1",
                    "tool_name": "read_file",
                    "arguments": [],
                    "working_path": r"D:\Projects\Demo",
                    "timeout_seconds": 30,
                },
            }
        )


def test_server_origin_normalization_has_an_explicit_origin_contract():
    assert normalize_server_origin("HTTP://Example.COM:80/") == "http://example.com"
    assert normalize_server_origin("https://example.com:8443") == "https://example.com:8443"
    with pytest.raises(ProtocolError, match="without a path"):
        normalize_server_origin("http://example.com/agentpark")


def test_standalone_operations_reuse_workspace_tool_contracts(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("first\nsecond\n", encoding="utf-8")
    operations = WorkspaceOperationRegistry()
    task = RemoteTask(
        task_id="task-read",
        tool_name="read_file",
        arguments={"file_path": "hello.txt", "start_line": 2},
        working_path=str(tmp_path),
        timeout_seconds=10,
    )

    result = json.loads(operations.execute(task))

    assert result["status"] == "success"
    assert result["content"] == "second\n"
    assert "ue_remote_control" not in operations.capabilities
    assert "cancer_control" not in operations.capabilities
    assert "list_directories" in operations.capabilities


def test_standalone_capabilities_share_the_remote_workspace_contract():
    operations = WorkspaceOperationRegistry()

    assert set(operations.capabilities) == set(STANDALONE_REMOTE_CAPABILITIES)
    assert REMOTE_FILE_SYSTEM_TOOL_NAMES <= set(operations.capabilities)


def test_standalone_operation_receives_remote_task_cancellation(tmp_path):
    operations = WorkspaceOperationRegistry()

    def waiting_operation(agent=None):
        while True:
            raise_if_cancel_requested(agent.cancel_event)
            agent.cancel_event.wait(0.01)

    operations._operations["rg_search_text"] = waiting_operation
    task = RemoteTask(
        task_id="task-cancel",
        tool_name="rg_search_text",
        arguments={},
        working_path=str(tmp_path),
        timeout_seconds=10,
    )
    cancel_event = threading.Event()
    result_holder = []
    thread = threading.Thread(
        target=lambda: result_holder.append(
            json.loads(operations.execute(task, cancel_event=cancel_event))
        )
    )
    thread.start()
    cancel_event.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert result_holder[0]["status"] == "stopped"


class _ScriptedTransport(JsonHttpTransport):
    def __init__(self) -> None:
        self.requests = []
        self.client = None

    def post(self, url, payload, *, timeout):
        self.requests.append((url, payload, timeout))
        if url.endswith("/register"):
            return {
                "ok": True,
                "worker_id": "worker-1",
                "token": "secret-token",
                "protocol_version": 2,
            }
        if url.endswith("/cancellations/poll"):
            return {"ok": True, "task_ids": []}
        if url.endswith("/poll"):
            return {
                "ok": True,
                "task": {
                    "task_id": "task-1",
                    "tool_name": "read_file",
                    "arguments": {"file_path": "hello.txt"},
                    "working_path": payload["working_path"] if "working_path" in payload else self.workspace,
                    "timeout_seconds": 5,
                },
            }
        if url.endswith("/result"):
            self.client.stop()
            return {"ok": True}
        raise AssertionError(f"unexpected request: {url}")


def test_client_registers_polls_executes_and_submits_result(tmp_path):
    (tmp_path / "hello.txt").write_text("remote content", encoding="utf-8")
    configuration = _configuration(tmp_path)
    configuration.configure_server("http://agentpark.example:8766")
    transport = _ScriptedTransport()
    transport.workspace = str(tmp_path)
    client = RemoteWorkerClient(
        configuration,
        WorkspaceOperationRegistry(),
        workspace_path=str(tmp_path),
        display_name="Test PC",
        transport=transport,
        retry_delay_seconds=0.01,
    )
    transport.client = client

    thread = threading.Thread(target=client.run_forever)
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()
    register = next(payload for url, payload, _ in transport.requests if url.endswith("/register"))
    assert register["host_kind"] == "standalone"
    assert "read_file" in register["capabilities"]
    assert "ue_remote_control" not in register["capabilities"]
    submitted = next(payload for url, payload, _ in transport.requests if url.endswith("/result"))
    assert submitted["token"] == "secret-token"
    assert submitted["result"]["ok"] is True
    decoded_result = json.loads(submitted["result"]["result"])
    assert decoded_result["content"] == "remote content"
