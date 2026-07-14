from __future__ import annotations

import json

import pytest


def test_cli_window_registration_and_visibility_status(monkeypatch, tmp_path):
    import src.companion_cli_window as cli_window
    from src.web_backend import runtime_paths

    monkeypatch.setattr(cli_window.os, "name", "nt")
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(cli_window, "_resolve_console_window_handle", lambda: 1234)
    monkeypatch.setattr(cli_window, "_is_window_visible", lambda handle: handle == 1234)
    monkeypatch.setattr(cli_window, "_is_window", lambda handle: handle == 1234)
    monkeypatch.setattr(cli_window, "_process_alive", lambda pid: pid == cli_window.os.getpid())

    registered = cli_window.register_companion_cli_window()
    status = cli_window.get_companion_cli_window_status()

    assert registered.running is True
    assert registered.handle == 1234
    assert status.running is True
    assert status.visible is True
    payload = json.loads((tmp_path / ".runtime" / cli_window.CLI_WINDOW_STATE_NAME).read_text(encoding="utf-8"))
    assert payload["pid"] == cli_window.os.getpid()
    assert payload["handle"] == "1234"

    cli_window.unregister_companion_cli_window()
    assert not (tmp_path / ".runtime" / cli_window.CLI_WINDOW_STATE_NAME).exists()


def test_cli_window_status_rejects_stale_process(monkeypatch, tmp_path):
    import src.companion_cli_window as cli_window
    from src.web_backend import runtime_paths

    monkeypatch.setattr(cli_window.os, "name", "nt")
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    state_path = tmp_path / ".runtime" / cli_window.CLI_WINDOW_STATE_NAME
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps({"pid": 999, "handle": "1234", "workspace_root": str(tmp_path)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_window, "_process_alive", lambda _pid: False)

    status = cli_window.get_companion_cli_window_status()

    assert status.running is False
    assert status.visible is False


def test_resolve_console_window_keeps_classic_console_handle(monkeypatch):
    import src.companion_cli_window as cli_window

    monkeypatch.setattr(cli_window, "_get_console_window", lambda: 1234)
    monkeypatch.setattr(cli_window, "_get_window_class_name", lambda handle: "ConsoleWindowClass")

    assert cli_window._resolve_console_window_handle() == 1234


def test_resolve_console_window_finds_windows_terminal_host(monkeypatch):
    import src.companion_cli_window as cli_window

    window_classes = {
        100: cli_window.PSEUDO_CONSOLE_WINDOW_CLASS,
        900: cli_window.WINDOWS_TERMINAL_WINDOW_CLASS,
    }
    monkeypatch.setattr(cli_window, "_get_console_window", lambda: 100)
    monkeypatch.setattr(cli_window, "_get_window_class_name", lambda handle: window_classes.get(handle, ""))
    monkeypatch.setattr(cli_window, "_get_ancestor_window", lambda handle, relationship: 900)

    assert cli_window._resolve_console_window_handle() == 900


def test_resolve_console_window_rejects_non_terminal_root_owner(monkeypatch):
    import src.companion_cli_window as cli_window

    monkeypatch.setattr(cli_window, "_get_console_window", lambda: 100)
    monkeypatch.setattr(
        cli_window,
        "_get_window_class_name",
        lambda handle: cli_window.PSEUDO_CONSOLE_WINDOW_CLASS if handle == 100 else "UnexpectedWindowClass",
    )
    monkeypatch.setattr(cli_window, "_get_ancestor_window", lambda handle, relationship: 900)

    with pytest.raises(RuntimeError, match="Windows Terminal window could not be resolved"):
        cli_window._resolve_console_window_handle()


def test_registration_hides_resolved_terminal_window(monkeypatch, tmp_path):
    import src.companion_cli_window as cli_window
    from src.web_backend import runtime_paths

    hidden = []
    monkeypatch.setattr(cli_window.os, "name", "nt")
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(cli_window, "_resolve_console_window_handle", lambda: 900)
    monkeypatch.setattr(cli_window, "_show_window", lambda handle, command: hidden.append((handle, command)))
    monkeypatch.setattr(cli_window, "_is_window_visible", lambda _handle: False)

    status = cli_window.register_companion_cli_window(start_hidden=True)

    assert status.handle == 900
    assert status.visible is False
    assert hidden == [(900, cli_window.SW_HIDE)]
    payload = json.loads((tmp_path / ".runtime" / cli_window.CLI_WINDOW_STATE_NAME).read_text(encoding="utf-8"))
    assert payload["handle"] == "900"
