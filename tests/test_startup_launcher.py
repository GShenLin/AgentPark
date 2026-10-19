"""Exercise the real batch recovery loop without a provider, build or live server."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows startup entry point")
@pytest.mark.parametrize("scenario,expected_exit,builds,repairs", [
    ("success", 0, 1, 0), ("repaired", 0, 2, 1),
    ("persistent", 42, 4, 3), ("repair_failed", 9, 1, 1),
])
def test_direct_build_launcher_owns_bounded_recovery(tmp_path, scenario, expected_exit, builds, repairs):
    root = tmp_path / "direct launch with spaces"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    canonical = (Path(__file__).resolve().parents[1] / "build_and_run.bat").read_text(encoding="utf-8")
    # Replace only the expensive preparation and interactive CLI subroutines.
    # The actual top-level recovery, logging, retry and readiness handoff run unchanged.
    start = canonical.index("\n:prepare_startup")
    end = canonical.index("\n:maybe_pause", start)
    outcome = "exit /b 0" if scenario == "success" else (
        'if exist "%~dp0repaired" exit /b 0\nexit /b 42' if scenario == "repaired" else "exit /b 42")
    prepare = (
        '\n:prepare_startup\necho build>>"%~dp0builds.txt"\n'
        'echo simulated build failure evidence\n' + outcome + '\n'
        ':run_companion\necho cli>"%~dp0cli.txt"\nexit /b 0\n'
    )
    (root / "build_and_run.bat").write_text(canonical[:start] + prepare + canonical[end:], encoding="utf-8")
    (scripts / "repair_startup.bat").write_text(
        '@echo off\nif not exist "%~1" exit /b 7\n'
        'findstr /c:"simulated build failure evidence" "%~1" >nul\nif errorlevel 1 exit /b 8\n'
        'echo repair>>"%~dp0../repairs.txt"\necho done>"%~dp0../repaired"\n'
        f'exit /b {9 if scenario == "repair_failed" else 0}\n', encoding="utf-8")
    env = {**os.environ, "AGENTPARK_NO_PAUSE": "1", "AGENTPARK_STARTUP_READY_FILE": str(root / "ready")}
    env.pop("AGENTPARK_STARTUP_LOG", None)
    result = subprocess.run(["cmd.exe", "/d", "/c", str(root / "build_and_run.bat")],
                            cwd=tmp_path, env=env, capture_output=True, timeout=15)
    assert result.returncode == expected_exit, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
    assert len((root / "builds.txt").read_text().splitlines()) == builds
    repair_file = root / "repairs.txt"
    assert (len(repair_file.read_text().splitlines()) if repair_file.exists() else 0) == repairs
    assert (root / "cli.txt").exists() is (expected_exit == 0)
    assert (root / "ready").exists() is (expected_exit == 0)
    transcript = next((root / ".runtime").glob("startup-*.log")).read_text()
    assert transcript.count("simulated build failure evidence") == builds
    assert transcript.count("Starting standalone Companion") == repairs
