from __future__ import annotations

import pytest

from nodes.codex_node.runtime import executable as app_server_client


def _windows_apps_codex() -> str:
    return r"C:\Program Files\WindowsApps\OpenAI.Codex\app\resources\codex.exe"


def test_resolve_command_uses_selected_native_executable(monkeypatch):
    bundled = r"C:\Users\agent\.codex\.sandbox-bin\codex.exe"

    monkeypatch.setattr(app_server_client.os, "name", "nt")
    monkeypatch.setattr(app_server_client.os.path, "expanduser", lambda value: r"C:\Users\agent" if value == "~" else value)
    monkeypatch.setattr(app_server_client.os.path, "isfile", lambda value: value == bundled)
    monkeypatch.setattr(
        app_server_client.shutil,
        "which",
        lambda value: bundled if value == "codex" else None,
    )

    assert app_server_client.resolve_executable("codex").path == bundled


def test_resolve_command_rejects_explicit_windows_apps_executable(monkeypatch):
    command = _windows_apps_codex()

    monkeypatch.setattr(app_server_client.os, "name", "nt")
    monkeypatch.setattr(app_server_client.os.path, "isfile", lambda value: value == command)

    with pytest.raises(ValueError, match="WindowsApps package executable"):
        app_server_client.resolve_executable(command)


def test_resolve_command_rejects_unlaunchable_windows_apps_path_without_fallback(monkeypatch):
    monkeypatch.setattr(app_server_client.os, "name", "nt")
    monkeypatch.setattr(app_server_client.os.path, "expanduser", lambda value: r"C:\Users\agent" if value == "~" else value)
    monkeypatch.setattr(app_server_client.os.path, "isfile", lambda _value: False)
    monkeypatch.setattr(app_server_client.shutil, "which", lambda _value: _windows_apps_codex())

    with pytest.raises(ValueError, match="Cannot find a launchable Codex command"):
        app_server_client.resolve_executable("codex")
