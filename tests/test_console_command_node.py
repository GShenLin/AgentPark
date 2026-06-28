import subprocess

from nodes.console_command_node import Node


class _FakePopen:
    def __init__(self, *, stdout="", stderr="", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        return self._stdout, self._stderr


def test_console_command_node_uses_shared_shell_and_timeout_parsing(monkeypatch):
    calls = []

    def _fake_popen(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return _FakePopen(stdout="ok\n", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = Node().on_input("", {"Command": "echo ok", "Shell": "false", "TimeoutSeconds": "1"})

    assert calls[0]["shell"] is False
    assert calls[0]["args"] == ["echo", "ok"]
    assert result["routes"][0]["payload"]["parts"][0]["text"] == "ok\n"
