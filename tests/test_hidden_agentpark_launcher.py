from __future__ import annotations

import os
import subprocess
import time

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows hidden launcher test")
def test_hidden_launcher_starts_build_script_with_spaced_workspace_path(tmp_path):
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    marker = workspace / "started.txt"
    (workspace / "build_and_run.bat").write_text(
        '@echo off\r\n>"%~dp0started.txt" echo started\r\n',
        encoding="utf-8",
    )
    launcher = os.path.abspath("scripts/start_agentpark_hidden.ps1")

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            launcher,
            "-WorkspaceRoot",
            str(workspace),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert int(completed.stdout.strip().splitlines()[-1]) > 0
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.read_text(encoding="utf-8").strip() == "started"
