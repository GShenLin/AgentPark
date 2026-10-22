"""Real process ownership and Codex writer-lock checks, without paid model calls."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from nodes.codex_node.runtime import app_server_client, executable, server_process
from nodes.codex_node.runtime.session_manager import CodexSessionManager, CodexSessionSpec, _ManagedSession
from src.harness.responses_gateway import HarnessResponsesGateway
from src.cli_provider_runtime.gateway_dispatch import GatewayDispatchResult
from src.cli_provider_runtime.contracts import CanonicalResult
from src.cli_provider_runtime.responses_wire import canonical_result_sse


@pytest.mark.skipif(os.name != "nt", reason="Windows npm entry point")
@pytest.mark.parametrize("managed", [False, True])
def test_npm_entry_resolves_native_binary_and_reports_broken_install(tmp_path, monkeypatch, managed):
    shim = tmp_path / "node_modules/.bin/codex.cmd" if managed else tmp_path / "codex.cmd"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text("official npm shim", encoding="utf-8")
    root = tmp_path / "node_modules/@openai/codex"
    root.mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "bin/codex.js").write_text("npm entry", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"name": "@openai/codex", "bin": {"codex": "bin/codex.js"}}))
    dependency = root / "node_modules/@openai/codex-win32-x64"
    binary = dependency / "vendor/x86_64-pc-windows-msvc/bin/codex.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"native")
    (dependency / "package.json").write_text('{}')
    monkeypatch.setattr(executable.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(executable.shutil, "which", lambda name: str(shim))
    resolved = executable.resolve_executable("codex")
    assert resolved.path == str(binary)
    assert resolved.environment()["CODEX_MANAGED_PACKAGE_ROOT"] == str(root.resolve())
    binary.unlink()
    with pytest.raises(ValueError, match="missing its executable"):
        executable.resolve_executable("codex")


def test_close_and_reopen_cannot_overlap(tmp_path):
    closing, release_close, created = threading.Event(), threading.Event(), threading.Event()
    order = []
    def close():
        closing.set()
        assert release_close.wait(5)
        order.append("closed")
    gateway = SimpleNamespace(release=lambda token: order.append("released"))
    manager = CodexSessionManager(gateway=gateway)
    spec = CodexSessionSpec("same", "provider", "model", "codex", str(tmp_path), "read-only", str(tmp_path / "state.json"))
    manager._sessions["same"] = _ManagedSession("old", SimpleNamespace(close=close),
                                               SimpleNamespace(token="lease"), "thread", threading.Lock())
    def create(spec, signature):
        order.append("created")
        created.set()
        return None
    manager._create_session = create
    closer = threading.Thread(target=manager.close_session, args=("same",))
    opener = threading.Thread(target=manager._session_for, args=(spec,))
    closer.start()
    assert closing.wait(5)
    opener.start()
    try:
        assert not created.wait(0.1)
    finally:
        release_close.set()
        closer.join(5)
        opener.join(5)
    assert order == ["closed", "released", "created"]


def test_failed_close_keeps_session_owned_and_prevents_replacement(tmp_path):
    def fail():
        raise OSError("Cannot terminate owned process")
    released = []
    manager = CodexSessionManager(gateway=SimpleNamespace(release=released.append))
    original = _ManagedSession("old", SimpleNamespace(close=fail),
                               SimpleNamespace(token="lease"), "thread", threading.Lock())
    manager._sessions["same"] = original
    with pytest.raises(OSError, match="Cannot terminate"):
        manager.close_session("same")
    assert manager._sessions["same"] is original
    assert not released


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    script = tmp_path / "rpc_server.py"
    pids = tmp_path / "pids.json"
    script.write_text('''import json, os, subprocess, sys
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
with open(sys.argv[1], 'w') as f: json.dump([os.getpid(), child.pid], f)
for line in sys.stdin:
    message = json.loads(line)
    if 'id' not in message: continue
    if sys.argv[2] == 'exit': sys.exit(2)
    response = {'id': message['id'], 'result': {}}
    if sys.argv[2] == 'reject': response = {'id': message['id'], 'error': {'message': 'initialization rejected'}}
    print(json.dumps(response), flush=True)
''', encoding="utf-8")
    original_popen = subprocess.Popen
    mode = ["ok"]
    processes = []
    def launch(argv, **kwargs):
        process = original_popen([sys.executable, "-u", str(script), str(pids), mode[0]], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(server_process.subprocess, "Popen", launch)
    monkeypatch.setattr(app_server_client, "resolve_executable", lambda command: executable.CodexExecutable(sys.executable))
    yield mode, pids, processes
    for process in processes:
        if process.poll() is None:
            process.kill()
    if pids.exists():
        for pid in json.loads(pids.read_text()):
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                pass


def assert_exited(pids):
    for pid in pids:
        try:
            psutil.Process(pid).wait(timeout=5)
        except psutil.NoSuchProcess:
            pass


def test_close_stops_descendants_and_closes_pipes(fake_server):
    _, path, _ = fake_server
    client = app_server_client.CodexAppServerClient()
    pids = json.loads(path.read_text())
    client.close()
    client.close()
    assert_exited(pids)
    assert not client.is_alive()
    assert all(pipe.closed for pipe in (client._proc.stdin, client._proc.stdout, client._proc.stderr))
    assert not client._stdout_thread.is_alive()
    assert not client._stderr_thread.is_alive()


def test_initialize_failure_cleans_server_and_descendants(fake_server):
    mode, path, processes = fake_server
    mode[0] = "reject"
    with pytest.raises(app_server_client.CodexAppServerError, match="initialization rejected"):
        app_server_client.CodexAppServerClient()
    assert_exited(json.loads(path.read_text()))
    assert processes[0].poll() is not None


def test_server_exit_during_initialize_reports_exit_and_cleans_child(fake_server):
    mode, path, processes = fake_server
    mode[0] = "exit"
    start = time.monotonic()
    with pytest.raises(app_server_client.CodexAppServerError, match="exited with code 2"):
        app_server_client.CodexAppServerClient()
    assert time.monotonic() - start < 5
    assert_exited(json.loads(path.read_text()))
    assert processes[0].poll() == 2


def test_reader_start_failure_still_cleans_process_tree(fake_server, monkeypatch):
    _, path, processes = fake_server
    original_start = threading.Thread.start
    def start(worker):
        if worker.name == "codex-app-server-stderr":
            raise RuntimeError("reader start failed")
        return original_start(worker)
    monkeypatch.setattr(threading.Thread, "start", start)
    with pytest.raises(RuntimeError, match="reader start failed"):
        app_server_client.CodexAppServerClient()
    assert processes[0].poll() is not None
    if path.exists():
        assert_exited(json.loads(path.read_text()))


@pytest.mark.skipif(os.name != "nt", reason="Windows Job ownership")
def test_job_assignment_failure_does_not_leave_server(monkeypatch):
    from src.harness.windows_job import WindowsJob
    processes = []
    original_popen = subprocess.Popen
    def launch(argv, **kwargs):
        p = original_popen([sys.executable, "-c", "import time; time.sleep(300)"], **kwargs)
        processes.append(p)
        return p
    def reject(*args):
        raise OSError("Job assignment rejected")
    monkeypatch.setattr(server_process.subprocess, "Popen", launch)
    monkeypatch.setattr(WindowsJob, "assign", reject)
    with pytest.raises(OSError, match="Job assignment rejected"):
        server_process.ServerProcess(executable.CodexExecutable(sys.executable))
    assert processes[0].poll() is not None


def require_codex():
    try:
        executable.resolve_executable("codex")
    except (ValueError, OSError):
        pytest.skip("Codex CLI not installed")


def test_real_config_changes_release_writer_before_resuming_same_thread(tmp_path, monkeypatch):
    require_codex()
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({"providers": {"local-test": {
        "type": "openai", "baseUrl": "http://unused.invalid/v1", "apiKey": "test",
        "model": "test-model", "supportmode": ["chat"],
    }}}), encoding="utf-8")
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config))
    monkeypatch.setattr("src.harness.responses_gateway.dispatch_responses", lambda config, payload:
        GatewayDispatchResult(status=200, content_type="text/event-stream", stream=canonical_result_sse(
            CanonicalResult(response_id="resp-lifecycle", text="LOCAL_LIFECYCLE_OK"))))
    gateway = HarnessResponsesGateway()
    manager = CodexSessionManager(gateway=gateway)
    spec = CodexSessionSpec(session_key="lifecycle", provider_id="local-test", model="test-model",
                            command="codex", cwd=str(tmp_path), sandbox="read-only",
                            state_path=str(tmp_path / "session.json"))
    old_processes = []
    try:
        assert manager.run_turn(spec, "Lifecycle test") == "LOCAL_LIFECYCLE_OK"
        first = manager._session_for(spec)
        thread_id = first.thread_id
        for web_search in ("cached", "disabled", "live"):
            old = manager._session_for(spec)
            old_processes.append(old.client._proc)
            spec = replace(spec, web_search=web_search)
            assert manager.run_turn(spec, "Continue lifecycle test") == "LOCAL_LIFECYCLE_OK"
            current = manager._session_for(spec)
            assert current.thread_id == thread_id
            assert old.client._proc.poll() is not None
            if os.name == "nt":
                assert psutil.Process(current.client._proc.pid).ppid() == os.getpid()
                assert psutil.Process(current.client._proc.pid).name().lower() == "codex.exe"
        manager.close_session(spec.session_key)
        assert current.client._proc.poll() is not None
        resumed = manager._session_for(spec)
        assert resumed.thread_id == thread_id
    finally:
        manager.close_all()
        gateway.close()
    assert all(p.poll() is not None for p in old_processes)


@pytest.mark.skipif(os.name != "nt", reason="Windows kill-on-owner-exit contract")
def test_owner_crash_stops_native_server_without_touching_other_processes(tmp_path):
    require_codex()
    root = Path(__file__).resolve().parents[1]
    ready = tmp_path / "server.json"
    source = (
        "import json,time; from pathlib import Path; "
        "from nodes.codex_node.runtime.app_server_client import CodexAppServerClient; "
        "client=CodexAppServerClient(); "
        f"Path({str(ready)!r}).write_text(json.dumps({{'pid':client._proc.pid}})); "
        "time.sleep(300)"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
    owner = subprocess.Popen([sys.executable, "-c", source], cwd=root,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 30
        while not ready.exists():
            assert owner.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        server = psutil.Process(json.loads(ready.read_text())["pid"])
        assert server.ppid() == owner.pid
        owner.kill()
        owner.wait(timeout=10)
        server.wait(timeout=10)
        assert unrelated.poll() is None
    finally:
        if owner.poll() is None:
            owner.kill()
        unrelated.kill()
        owner.wait(timeout=10)
        unrelated.wait(timeout=10)
