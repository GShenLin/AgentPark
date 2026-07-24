import http.client
import json
import threading
from pathlib import Path

import pytest

from src.remote_worker.client import JsonHttpTransport, RemoteWorkerClient
from src.remote_worker.discovery import DiscoveryServer
from src.remote_worker.identity import IdentityStore, WorkerConfiguration
from src.remote_worker.operations import StandaloneOperationRegistry
from src.remote_worker.protocol import ProtocolError, RemoteTask, normalize_server_origin


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


def test_discovery_accepts_only_the_matching_browser_origin():
    configured = []
    server = DiscoveryServer(configured.append, port=0)
    server.start()
    host, port = server.address
    try:
        connection = http.client.HTTPConnection(host, port, timeout=3)
        body = json.dumps({"server_url": "http://10.0.0.5:8766"})
        connection.request(
            "POST",
            "/agentpark/discover",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body.encode("utf-8"))),
                "Origin": "http://10.0.0.5:8766",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload == {"ok": True, "server_url": "http://10.0.0.5:8766"}
        assert configured == ["http://10.0.0.5:8766"]

        connection.request(
            "POST",
            "/agentpark/discover",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body.encode("utf-8"))),
                "Origin": "http://malicious.example",
            },
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 403
        assert configured == ["http://10.0.0.5:8766"]
    finally:
        server.stop()


def test_standalone_operations_reuse_workspace_tool_contracts(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("first\nsecond\n", encoding="utf-8")
    operations = StandaloneOperationRegistry(folder_picker=lambda initial: initial)
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
    assert "select_folder" in operations.capabilities


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
                "protocol_version": 1,
            }
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
        StandaloneOperationRegistry(folder_picker=lambda initial: initial),
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
