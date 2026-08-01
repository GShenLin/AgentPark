from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


def _write_settings(tmp_path, network: object) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps({"network": network}),
        encoding="utf-8",
    )


def test_project_proxy_is_applied_to_parent_and_inherited_by_child(monkeypatch, tmp_path):
    from src import project_process_environment
    from src import workspace_settings

    _write_settings(
        tmp_path,
        {
            "httpProxy": "http://127.0.0.1:17891",
            "noProxy": "localhost,127.0.0.1,::1",
        },
    )
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        project_process_environment,
        "load_workspace_settings",
        workspace_settings.load_workspace_settings,
    )
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)

    applied = project_process_environment.apply_project_process_environment()
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json,os;"
                "print(json.dumps({k:os.environ.get(k,'') "
                "for k in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY')}))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert applied == {
        "HTTP_PROXY": "http://127.0.0.1:17891",
        "HTTPS_PROXY": "http://127.0.0.1:17891",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }
    assert json.loads(child.stdout) == applied


def test_project_proxy_rejects_invalid_url():
    from src.project_process_environment import read_project_proxy_settings

    with pytest.raises(ValueError, match="absolute http"):
        read_project_proxy_settings({"network": {"httpProxy": "127.0.0.1:17891"}})


def test_missing_project_proxy_preserves_inherited_environment(monkeypatch):
    from src.project_process_environment import apply_project_process_environment

    monkeypatch.setenv("HTTP_PROXY", "http://parent:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://parent:8080")
    monkeypatch.setenv("NO_PROXY", "localhost")

    applied = apply_project_process_environment({})

    assert applied == {
        "HTTP_PROXY": "http://parent:8080",
        "HTTPS_PROXY": "http://parent:8080",
        "NO_PROXY": "localhost",
    }
