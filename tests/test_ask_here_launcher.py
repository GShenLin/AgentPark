from pathlib import Path
import pytest
from src import ask_here_launcher


def test_ping_uses_lightweight_graph_health_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr(ask_here_launcher, "resolve_server_base_url", lambda: "http://127.0.0.1:8788")
    monkeypatch.setattr(ask_here_launcher, "_request_json", lambda method, url, **kwargs: calls.append((method, url)) or {"graphs": []})
    assert ask_here_launcher.main(["ping"]) == 0
    assert calls == [("GET", "http://127.0.0.1:8788/api/graphs")]


@pytest.mark.parametrize("is_file", [False, True])
def test_dispatch_routes_working_directory_to_companion(monkeypatch, tmp_path, is_file):
    target = tmp_path / "sample.txt" if is_file else tmp_path
    if is_file:
        target.write_text("hello", encoding="utf-8")
    calls = []
    monkeypatch.setattr(ask_here_launcher, "dispatch_to_companion_cli", lambda path: calls.append(path) or {"mode": "companion_cli", "pid": 123})
    monkeypatch.setattr(ask_here_launcher, "_debug_log", lambda *args, **kwargs: None)
    result = ask_here_launcher.dispatch_folder(str(target))
    assert calls == [str(tmp_path)]
    assert result == {"path": str(target), "mode": "companion_cli", "pid": 123}


def test_dispatch_rejects_missing_path(tmp_path):
    with pytest.raises(ask_here_launcher.AskHereError, match="does not exist"):
        ask_here_launcher.dispatch_folder(str(tmp_path / "missing"))
