import subprocess
import importlib.util
from io import BytesIO
from pathlib import Path
from threading import Thread
import time

from nodes.console_command_node import Node


class _FakePopen:
    def __init__(self, *, stdout=b"", stderr=b"", returncode=0):
        self.stdout = BytesIO(stdout)
        self.stderr = BytesIO(stderr)
        self.stdin = BytesIO()
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def test_console_command_node_uses_shared_shell_and_timeout_parsing(monkeypatch):
    calls = []

    def _fake_popen(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return _FakePopen(stdout=b"ok\n", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = Node().on_input("", {"Command": "echo ok", "Shell": "false", "TimeoutSeconds": "1"})

    assert calls[0]["shell"] is False
    assert calls[0]["args"] == ["echo", "ok"]
    assert result["routes"][0]["payload"]["parts"][0]["text"] == "ok\n"


def test_console_command_node_timeout_zero_disables_deadline(monkeypatch):
    class SlowFakePopen:
        def __init__(self):
            self.returncode = 0
            self.poll_count = 0
            self.terminated = False
            self.killed = False
            self.stdout = BytesIO(b"done\n")
            self.stderr = BytesIO()
            self.stdin = BytesIO()

        def poll(self):
            self.poll_count += 1
            if self.poll_count < 3:
                return None
            return self.returncode

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return self.returncode

    fake_proc = SlowFakePopen()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: fake_proc)
    monkeypatch.setattr("nodes.console_command_node.time.sleep", lambda _seconds: None)

    result = Node().on_input("", {"Command": "slow", "TimeoutSeconds": "0"})

    assert fake_proc.terminated is False
    assert fake_proc.killed is False
    assert result["routes"][0]["payload"]["parts"][0]["text"] == "done\n"
    assert result["routes"][2]["payload"]["parts"][0]["text"] == "0"


def test_console_command_node_decodes_utf8_when_configured():
    raw = "交互输入测试脚本\n".encode("utf-8")

    assert Node._decode_bytes(raw, "utf-8") == "交互输入测试脚本\n"


def test_console_command_interactive_sessions_are_shared_across_dynamic_import(monkeypatch):
    class InteractiveStdin:
        def __init__(self, proc):
            self.proc = proc
            self.written = b""

        def write(self, data):
            self.written += bytes(data)
            self.proc.returncode = 0

        def flush(self):
            return None

        def close(self):
            return None

    class InteractiveFakePopen:
        def __init__(self, *_args, **_kwargs):
            self.stdout = BytesIO()
            self.stderr = BytesIO()
            self.returncode = None
            self.stdin = InteractiveStdin(self)

        def poll(self):
            return self.returncode

        def terminate(self):
            if self.returncode is None:
                self.returncode = -15

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    node_path = Path(__file__).resolve().parents[1] / "nodes" / "console_command_node.py"
    spec = importlib.util.spec_from_file_location("dynamic_console_command_node_test", node_path)
    assert spec and spec.loader
    dynamic_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dynamic_module)

    fake_proc = InteractiveFakePopen()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: fake_proc)

    events = []

    def stream_callback(payload):
        events.append(dict(payload))

    thread = Thread(
        target=lambda: dynamic_module.Node().on_input(
            "",
            {
                "Command": "interactive",
                "Interactive": True,
                "CloseStdin": False,
                "TimeoutSeconds": 0,
                "stream_callback": stream_callback,
            },
        ),
        daemon=True,
    )
    thread.start()

    deadline = time.monotonic() + 2.0
    session_id = ""
    while time.monotonic() < deadline:
        for event in events:
            payload = event.get("event") if isinstance(event.get("event"), dict) else {}
            if payload.get("type") == "stdin_ready":
                session_id = str(payload.get("session_id") or "")
                break
        if session_id:
            break
        time.sleep(0.01)

    assert session_id
    assert Node.send_interactive_input(session_id, "Alice", append_newline=True) is True
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert fake_proc.stdin.written == b"Alice\n"
