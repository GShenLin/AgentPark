"""Real HTTP control plane and two independently owned remote workspaces."""
import json
import socket
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
import uvicorn

from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.remote_worker.protocol import RemoteTask
from src.remote_workspace.operations import WorkspaceOperationRegistry
from src.tool.base_tool import BaseTool
from src.web_backend.remote_workspace_api import RemoteWorkspaceApiDomain


def test_read_device_a_write_and_execute_on_b_then_return_local(tmp_path, monkeypatch):
    local, a, b = (tmp_path / name for name in ("local", "a", "b"))
    for path in (local, a, b):
        path.mkdir()
    (a / "requirements.txt").write_text("Return the sum of two inputs.\n", encoding="utf-8")
    (b / "AGENTS.md").write_text("Keep the implementation in solution.py.\n", encoding="utf-8")
    api = RemoteWorkspaceApiDomain()
    app = FastAPI()
    app.get("/api/remote-workers")(api.list_workers)
    app.post("/api/remote-workers/internal/execute")(api.execute_internal)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    monkeypatch.setenv("AGENTPARK_SERVER_PORT", str(sock.getsockname()[1]))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    server_thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    server_thread.start()
    stop = threading.Event()
    seen, failures, workers = [], [], []
    operations = WorkspaceOperationRegistry()
    for name, path in (("A", a), ("B", b)):
        api.broker.register({"protocol_version": 2, "worker_id": name, "token": "test-token",
                             "display_name": name, "host_kind": "standalone", "workspace_path": str(path),
                             "capabilities": list(operations.capabilities)}, "127.0.0.1")
        def worker(worker_id=name):
            try:
                while not stop.is_set():
                    task = api.broker.poll(worker_id, "test-token", .1)
                    if task is None:
                        continue
                    seen.append((worker_id, task["tool_name"], task["working_path"]))
                    value = operations.execute(RemoteTask.from_poll_response({"ok": True, "task": task}))
                    api.broker.submit_result(worker_id, "test-token", task["task_id"], {"ok": True, "result": value})
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start(); workers.append(thread)
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        agent = SimpleNamespace(config={"working_path": str(local)})
        bind_agent_runtime_context(agent, AgentRuntimeContext(working_path=str(local)))
        tool = BaseTool(agent)
        for module in ("execution_device_tools", "file_read_tools", "file_write_tools", "console_tools"):
            tool.addTool(module)
        def call(name, **args):
            result = json.loads(tool.execute_tool(name, args))
            assert result.get("status") == "success", result
            return result
        catalog = call("list_execution_devices")
        assert catalog["current"]["device_id"] == "local"
        assert {item["device_id"] for item in catalog["devices"]} == {"local", "A", "B"}
        call("switch_execution_device", device_id="A", working_path=str(a), expected_revision=0)
        requirement = call("read_file", file_path="requirements.txt")["content"]
        target = call("switch_execution_device", device_id="B", working_path=str(b), expected_revision=1)
        assert "solution.py" in target["current"]["workspace"]["project_instructions"]["text"]
        assert "sum" in requirement
        call("write_file", file_path="solution.py", content="def add(a, b):\n    return a + b\n")
        result = call("execute_console_command", command='python -c "from solution import add; assert add(2, 3) == 5; print(5)"')
        assert "5" in result["stdout"]
        call("switch_execution_device", device_id="A", working_path=str(a), expected_revision=2)
        assert call("read_file", file_path="requirements.txt")["content"] == requirement
        call("switch_execution_device", device_id="local", working_path=str(local), expected_revision=3)
        call("write_file", file_path="done.txt", content="B verified")
        assert (local / "done.txt").read_text() == "B verified"
        assert (b / "solution.py").is_file()
        assert not (a / "solution.py").exists() and not (local / "solution.py").exists()
        assert ("A", "read_file", str(a)) in seen
        assert ("B", "write_file", str(b)) in seen
        assert ("B", "execute_console_command", str(b)) in seen
        assert not failures
    finally:
        stop.set()
        for thread in workers:
            thread.join(2)
        api.close()
        server.should_exit = True
        server_thread.join(5)
        sock.close()
    assert not server_thread.is_alive() and not failures
