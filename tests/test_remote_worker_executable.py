import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

class _ProtocolState:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.registration = None
        self.results = {}
        self.tasks = [
            ("read", "read_file", {"file_path": "remote.txt"}),
            ("write", "write_file", {"file_path": "generated.txt", "content": "generated remote"}),
            (
                "search",
                "rg_search_text",
                {"query": "from packaged remote", "include_globs": ["*.txt"], "fixed_strings": True},
            ),
            ("list", "rg_list_files", {"include_globs": ["*.txt"]}),
            (
                "patch",
                "apply_patch",
                {
                    "patch": (
                        "*** Begin Patch\n"
                        "*** Update File: remote.txt\n"
                        "@@\n"
                        "-from packaged remote\n"
                        "+from packaged remote patched\n"
                        "*** End Patch"
                    )
                },
            ),
            ("command", "execute_console_command", {"command": "Write-Output 'remote-command-ok'"}),
        ]
        self.next_task = 0
        self.result_event = threading.Event()


def _handler_type(state: _ProtocolState):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/remote-workers/register":
                state.registration = payload
                self._respond(
                    {
                        "ok": True,
                        "worker_id": "executable-worker",
                        "token": "executable-secret",
                        "protocol_version": 1,
                    }
                )
                return
            if self.path == "/api/remote-workers/executable-worker/poll":
                task = None
                if state.next_task < len(state.tasks):
                    task_id, tool_name, arguments = state.tasks[state.next_task]
                    state.next_task += 1
                    task = {
                        "task_id": task_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "working_path": str(state.workspace),
                        "timeout_seconds": 10,
                    }
                self._respond({"ok": True, "task": task})
                return
            result_prefix = "/api/remote-workers/executable-worker/tasks/"
            if self.path.startswith(result_prefix) and self.path.endswith("/result"):
                task_id = self.path[len(result_prefix) : -len("/result")]
                state.results[task_id] = payload
                if len(state.results) == len(state.tasks):
                    state.result_event.set()
                self._respond({"ok": True})
                return
            if self.path == "/api/remote-workers/executable-worker/heartbeat":
                self._respond({"ok": True})
                return
            self._respond({"ok": False}, status=404)

        def _respond(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return Handler


def test_packaged_remote_worker_executes_protocol_task(tmp_path):
    executable_value = str(os.environ.get("AGENTPARK_REMOTE_EXE") or "").strip()
    if not executable_value:
        pytest.skip("set AGENTPARK_REMOTE_EXE to run the packaged worker test")
    executable = Path(executable_value).resolve()
    assert executable.is_file()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "remote.txt").write_text("from packaged remote", encoding="utf-8")
    state = _ProtocolState(workspace)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_type(state))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]
    process = subprocess.Popen(
        [
            str(executable),
            "--server",
            f"http://127.0.0.1:{port}",
            "--workspace",
            str(workspace),
            "--state-directory",
            str(tmp_path / "state"),
            "--discovery-port",
            "0",
        ],
    )
    try:
        assert state.result_event.wait(timeout=30), "packaged worker did not submit a result"
        assert state.registration["host_kind"] == "standalone"
        assert "read_file" in state.registration["capabilities"]
        assert set(state.results) == {task_id for task_id, _, _ in state.tasks}
        decoded = {}
        for task_id, payload in state.results.items():
            assert payload["token"] == "executable-secret"
            assert payload["result"]["ok"] is True
            decoded[task_id] = json.loads(payload["result"]["result"])
        assert decoded["read"]["content"] == "from packaged remote"
        assert decoded["write"]["status"] == "success"
        assert decoded["search"]["status"] == "success"
        assert decoded["search"]["matches"]
        assert decoded["list"]["status"] == "success"
        assert decoded["list"]["files"]
        assert decoded["patch"]["status"] == "success"
        assert decoded["command"]["status"] == "success"
        assert "remote-command-ok" in decoded["command"]["stdout"]
        assert (workspace / "remote.txt").read_text(encoding="utf-8") == "from packaged remote patched"
    finally:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.terminate()
        process.wait(timeout=10)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
