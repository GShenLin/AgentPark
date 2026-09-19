from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.startup_health import probe_server, wait_for_server
from src.startup_repair import build_repair_config, build_repair_prompt


def test_repair_uses_explicit_companion_model_but_local_standalone_tools(tmp_path):
    config = build_repair_config({
        "provider_id": "p", "model": "second", "reasoning_effort": "high",
        "remote_enabled": True, "remote_worker_id": "colleague", "working_path": "D:/other",
        "mcp_servers": ["agentpark-companion"], "plugins": ["remote-plugin"],
    }, tmp_path, {"p": {"models": ["first", "second"]}})
    assert config["provider_id"] == "p" and config["model"] == "second"
    assert config["working_path"] == str(tmp_path.resolve())
    assert config["remote_enabled"] is False
    assert config["mcp_servers"] == config["plugins"] == config["skills"] == []
    assert "console_tools" in config["tools"] and "apply_patch_tool" in config["tools"]
    assert config["reasoning_effort"] == "high"


@pytest.mark.parametrize("source", [
    {"provider_id": "p"}, {"provider_id": "p", "model": "wrong"},
    {"provider_id": "absent", "model": "m"}, {"provider_id": "p", "model": ["m"]},
])
def test_repair_rejects_missing_or_invalid_model_binding(source, tmp_path):
    with pytest.raises(ValueError):
        build_repair_config(source, tmp_path, {"p": {"models": ["m"]}})


def test_failure_context_includes_build_and_server_errors(tmp_path):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    log = runtime / "restart-worker-123.log"
    log.write_text("x" * 30000 + "\n编译失败: error TS2322", encoding="utf-8-sig")
    (runtime / "agentpark-server.err.log").write_text("ImportError: broken module", encoding="utf-8")
    prompt = build_repair_prompt(tmp_path, log)
    assert "编译失败: error TS2322" in prompt and "ImportError: broken module" in prompt
    assert "Log not present" in prompt
    assert len(prompt) < 26000


def test_health_checks_actual_http_server_and_expected_process(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/system/status"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "instance_id": "new", "pid": 123}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    identity = {"app": "AgentPark", "pid": 123, "host": "0.0.0.0", "port": server.server_port,
                "workspace_root": str(tmp_path)}
    path = runtime / "agentpark-server.pid"
    path.write_text(json.dumps(identity), encoding="utf-8")
    try:
        assert probe_server(tmp_path, 123)["instance_id"] == "new"
        with pytest.raises(ValueError, match="newly launched"):
            probe_server(tmp_path, 999)
        identity["pid"] = 999
        path.write_text(json.dumps(identity), encoding="utf-8")
        with pytest.raises(ValueError, match="HTTP status"):
            probe_server(tmp_path, 999)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_readiness_failure_contains_probe_evidence(tmp_path):
    with pytest.raises(TimeoutError, match="FileNotFoundError"):
        wait_for_server(tmp_path, 123, timeout=0.01)


def test_repair_turn_runs_without_web_server_and_persists_its_selected_model(monkeypatch, tmp_path):
    from src import startup_repair, workspace_settings
    from src.config_loader import ConfigLoader
    from src.web_backend import runtime_paths
    from src.cli_commands import chat
    from src import project_process_environment

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(project_process_environment, "apply_project_process_environment", lambda: None)
    monkeypatch.setattr(ConfigLoader, "get_all_providers", lambda self: {"p": {"models": ["a", "b"]}})
    source = tmp_path / "memories" / "Companion" / "Companion" / "config.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"provider_id":"p","model":"b","remote_enabled":true}', encoding="utf-8")
    log = tmp_path / "failed.log"
    log.write_text("compiler error TS2322", encoding="utf-8")
    calls = []

    def run(target, prompt, *, print_stream):
        calls.append((target, prompt, print_stream))
        assert target.config["model"] == "b"
        assert target.config["remote_enabled"] is False
        assert "compiler error TS2322" in prompt

    monkeypatch.setattr(chat, "_run_one_turn", run)
    startup_repair.run_repair(tmp_path, log)
    assert len(calls) == 1
    assert Path(calls[0][0].config_path).is_relative_to(tmp_path / ".runtime" / "startup-repair")
    assert json.loads(source.read_text())["remote_enabled"] is True
    assert Path(calls[0][0].config_path).with_name("failure-context.txt").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows batch process quoting")
def test_batch_server_launch_preserves_workspace_paths_with_spaces(tmp_path):
    root = tmp_path / "workspace with spaces"
    (root / "src").mkdir(parents=True)
    (root / "src" / "__init__.py").touch()
    (root / "src" / "fast_api.py").write_text(
        "import json, pathlib, sys\npathlib.Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8")
    canonical = Path(__file__).resolve().parents[1] / "build_and_run.bat"
    command = next(line for line in canonical.read_text().splitlines() if "$serverProcess=Start-Process" in line)
    script = root / "launch.bat"
    script.write_text("@echo off\n" + command + "\nexit /b %errorlevel%\n", encoding="utf-8")
    env = {**os.environ, "AGENTPARK_PYTHON_EXE": sys.executable, "AGENTPARK_WORKSPACE_ROOT": str(root),
           "AGENTPARK_WEB_STDOUT": str(root / "out.log"), "AGENTPARK_WEB_STDERR": str(root / "err.log"),
           "AGENTPARK_STARTED_PROCESS_FILE": str(root / "started.pid")}
    result = subprocess.run(["cmd.exe", "/d", "/c", str(script)], env=env, cwd=root, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert int((root / "started.pid").read_text(encoding="utf-8-sig").strip()) > 0
    # Start-Process has returned; wait for this tiny isolated child to write argv.
    import time
    deadline = time.monotonic() + 5
    while not (root / "arguments.json").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert json.loads((root / "arguments.json").read_text()) == ["--workspace-root", str(root)]


@pytest.mark.skipif(os.name != "nt", reason="Windows canonical build failure integration")
def test_canonical_build_records_failure_and_preserves_exit_code(tmp_path):
    import shutil
    root = tmp_path / "isolated build"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (root / "webui").mkdir()
    binaries = root / "bin"
    binaries.mkdir()
    (scripts / "sync_before_restart.ps1").write_text("exit 0\n", encoding="utf-8")
    (binaries / "rg.cmd").write_text("@exit /b 0\n", encoding="utf-8")
    (binaries / "npm.cmd").write_text(
        '@echo off\nif "%~1"=="install" exit /b 0\necho error TS2322: intentional fixture failure\nexit /b 42\n',
        encoding="utf-8")
    (scripts / "bootstrap_windows_toolchain.bat").write_text(
        f'@set "PYTHON_EXE={sys.executable}"\n@exit /b 0\n', encoding="utf-8")
    canonical = Path(__file__).resolve().parents[1] / "build_and_run.bat"
    shutil.copyfile(canonical, root / "build_and_run.bat")
    log = root / "build.log"
    env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
           "AGENTPARK_NO_PAUSE": "1", "AGENTPARK_STARTUP_LOG": str(log)}
    result = subprocess.run(["cmd.exe", "/d", "/c", str(root / "build_and_run.bat")],
                            env=env, cwd=root, capture_output=True, timeout=15)
    assert result.returncode == 42, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
    transcript = log.read_text(encoding="utf-8")
    assert "error TS2322: intentional fixture failure" in transcript
    assert "Starting AgentPark CLI" not in transcript


@pytest.mark.skipif(os.name != "nt", reason="Windows restart worker integration")
@pytest.mark.parametrize("scenario,expected_code,builds,repairs", [
    ("success", 0, 1, 0), ("repaired", 0, 2, 1),
    ("persistent", 1, 4, 3), ("repair_failed", 1, 1, 1),
])
def test_restart_worker_repairs_and_rebuilds_in_isolated_workspace(tmp_path, scenario, expected_code, builds, repairs):
    root = tmp_path / "workspace with spaces"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "restart_agentpark.ps1").write_text("exit 0\n", encoding="utf-8")
    build_result = "exit /b 0" if scenario == "success" else (
        'if exist "%~dp0repaired" exit /b 0\nexit /b 42' if scenario == "repaired" else "exit /b 42")
    (root / "build_and_run.bat").write_text(
        '@echo off\necho build>>"%~dp0builds.txt"\necho simulated compiler error TS2322>"%AGENTPARK_STARTUP_LOG%"\n' + build_result + "\n",
        encoding="utf-8")
    repair_result = "exit /b 9" if scenario == "repair_failed" else "exit /b 0"
    (scripts / "repair_startup.bat").write_text(
        '@echo off\nif not exist "%~1" exit /b 7\necho repair>>"%~dp0..\\repairs.txt"\n'
        'echo done>"%~dp0..\\repaired"\n' + repair_result + "\n", encoding="utf-8")
    worker = Path(__file__).resolve().parents[1] / "scripts" / "restart_agentpark_worker.ps1"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(worker),
                             "-WorkspaceRoot", str(root)], capture_output=True, timeout=30)
    assert result.returncode == expected_code, result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")
    assert len((root / "builds.txt").read_text().splitlines()) == builds
    repair_file = root / "repairs.txt"
    assert (len(repair_file.read_text().splitlines()) if repair_file.exists() else 0) == repairs
    log = next((root / ".runtime").glob("restart-worker-*.log")).read_text(encoding="utf-8-sig")
    assert "Build transcript:" in log
    if repairs:
        assert "simulated compiler error TS2322" in log
        assert "standalone Companion" in log


@pytest.mark.skipif(os.name != "nt", reason="Windows restart concurrency integration")
def test_duplicate_restart_does_not_stop_or_build_twice(tmp_path):
    import time
    root = tmp_path / "duplicate restart"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "restart_agentpark.ps1").write_text(
        "Add-Content -LiteralPath (Join-Path $PSScriptRoot '../stops.txt') -Value stop\nexit 0\n", encoding="utf-8")
    (root / "build_and_run.bat").write_text(
        '@echo off\necho build>>"%~dp0builds.txt"\n'
        'powershell -NoProfile -Command "Start-Sleep -Seconds 3"\nexit /b 0\n', encoding="utf-8")
    worker = Path(__file__).resolve().parents[1] / "scripts" / "restart_agentpark_worker.ps1"
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(worker), "-WorkspaceRoot", str(root)]
    first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not (root / "builds.txt").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (root / "builds.txt").exists()
        duplicate = subprocess.run(command, capture_output=True, timeout=10)
        assert duplicate.returncode == 0
        assert b"duplicate request ignored" in duplicate.stdout
        first.communicate(timeout=15)
        assert first.returncode == 0
        assert (root / "builds.txt").read_text().splitlines() == ["build"]
        assert (root / "stops.txt").read_text().splitlines() == ["stop"]
        # An exited worker releases its OS lock so subsequent restarts work.
        again = subprocess.run(command, capture_output=True, timeout=15)
        assert again.returncode == 0
        assert (root / "builds.txt").read_text().splitlines() == ["build", "build"]
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate(timeout=5)
