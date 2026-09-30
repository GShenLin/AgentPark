from tests.agent_invocation_helpers import configured_fake
import json
import base64
import os
from pathlib import Path
import shlex
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from functions.console_session_registry import console_session_scope, registry_for
from functions.console_session_tools import (
    start_console_session, read_console_session, wait_console_session, stop_console_session,
)
from nodes.agent_stream_runtime import AgentStreamRuntime


def command(script):
    # Windows PowerShell 5's native argv binding strips nested literal double quotes.
    # Keep test payload syntax out of that separate shell quoting concern.
    encoded = base64.b64encode(script.encode('utf-8')).decode('ascii')
    script = f"import base64; exec(base64.b64decode('{encoded}'))"
    if os.name == "nt":
        return f"& '{sys.executable}' -u -c '{script.replace(chr(39), chr(39)*2)}'"
    return f"{shlex.quote(sys.executable)} -u -c {shlex.quote(script)}"


@pytest.fixture
def agent(tmp_path):
    agent = SimpleNamespace(config={"working_path": str(tmp_path)}, cancel_event=threading.Event())
    with console_session_scope(agent):
        yield agent


def start(agent, script, timeout=20):
    result = json.loads(start_console_session(command(script), timeout_seconds=timeout, agent=agent))
    assert "session_id" in result, result
    return result["session_id"]


def test_incremental_output_replay_utf8_and_exit_code(agent):
    sid = start(agent, "import os,time,sys; b='中文😀'.encode(); os.write(1,b[:2]); time.sleep(.1); os.write(1,b[2:]); print('x'*25000); print('错误',file=sys.stderr); sys.exit(7)")
    result = json.loads(wait_console_session(sid, wait_seconds=10, max_chars=43, agent=agent))
    assert result["finished"] and result["returncode"] == 7 and result["status"] == "error"
    assert result["has_more_output"]
    first = result["stdout"]
    assert json.loads(read_console_session(sid, max_chars=43, agent=agent))["stdout"] == first
    stdout, stderr = result["stdout"], result["stderr"]
    while result["has_more_output"]:
        result = json.loads(read_console_session(sid, cursor=result["next_cursor"], max_chars=4096, agent=agent))
        stdout += result["stdout"]; stderr += result["stderr"]
    assert stdout.strip() == '中文😀' + 'x'*25000
    assert stderr.strip() == '错误'
    assert json.loads(read_console_session(sid, cursor=result["next_cursor"], agent=agent))["stdout"] == ""


def test_live_output_is_visible_before_exit_and_wait_does_not_kill(agent):
    sid = start(agent, "import time; print('ready',flush=True); time.sleep(3); print('done')")
    until = time.monotonic() + 5
    while True:
        result = json.loads(read_console_session(sid, agent=agent))
        if 'ready' in result["stdout"]:
            break
        assert time.monotonic() < until
        time.sleep(.05)
    assert not result["finished"]
    peek = json.loads(wait_console_session(sid, cursor=result["next_cursor"], wait_seconds=0, agent=agent))
    assert peek["status"] == "running"
    final = json.loads(wait_console_session(sid, cursor=peek["next_cursor"], wait_seconds=10, agent=agent))
    assert final["status"] == "success" and 'done' in final["stdout"]


def test_session_ownership_cursor_binding_and_validation(agent, tmp_path):
    sid = start(agent, "print('one')")
    other = SimpleNamespace(config={"working_path": str(tmp_path)})
    with console_session_scope(other):
        assert json.loads(read_console_session(sid, agent=other))["status"] == "invalid_arguments"
    cursor = {"session_id": "other", "stdout": 0, "stderr": 0}
    assert json.loads(read_console_session(sid, cursor=cursor, agent=agent))["status"] == "invalid_arguments"
    for kwargs in ({"wait_seconds": -1}, {"wait_seconds": True}, {"max_chars": 0}):
        assert json.loads(wait_console_session(sid, agent=agent, **kwargs))["status"] == "invalid_arguments"


@pytest.mark.parametrize("mode", ["stop", "timeout", "cancel", "scope"])
def test_termination_kills_descendant_and_cleans_spools(agent, tmp_path, mode):
    child = "import time,pathlib; time.sleep(3); pathlib.Path('leaked').write_text('bad')"
    script = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); print('spawned',flush=True); time.sleep(30)"
    sid = start(agent, script, timeout=1 if mode == "timeout" else 20)
    session = registry_for(agent).get(sid)
    spool, launch = Path(session.directory.name), session.launch.directory
    until = time.monotonic() + 5
    while 'spawned' not in json.loads(read_console_session(sid, agent=agent)).get('stdout', ''):
        assert not session.done.is_set(), session.snapshot(None, 8000)
        assert time.monotonic() < until
        time.sleep(.02)
    if mode == "stop":
        result = json.loads(stop_console_session(sid, agent=agent))
    elif mode == "scope":
        registry_for(agent).close()
        result = {"status": session.status}
        assert not spool.exists()
    else:
        if mode == "cancel":
            agent.cancel_event.set()
        assert session.done.wait(10)
        result = json.loads(read_console_session(sid, agent=agent))
    assert result["status"] == ("timeout" if mode == "timeout" else "stopped")
    if launch:
        assert not Path(launch.name).exists()
    time.sleep(3.2)
    assert not (tmp_path / 'leaked').exists()


def test_background_child_is_owned_after_parent_exits(agent, tmp_path):
    child = "import time,pathlib; time.sleep(2); pathlib.Path('orphan').write_text('bad')"
    sid = start(agent, f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)")
    result = json.loads(wait_console_session(sid, wait_seconds=10, agent=agent))
    if os.name == 'nt':
        assert result["status"] == "error" and 'child processes' in result['error'], result
    else:
        assert result['status'] == 'success', result
    time.sleep(2.2)
    assert not (tmp_path/'orphan').exists()


def test_invalid_encoding_is_explicit_error(agent):
    sid = start(agent, "import os; os.write(1,bytes([255]))")
    result = json.loads(wait_console_session(sid, wait_seconds=10, agent=agent))
    assert result["status"] == "error" and "UnicodeDecodeError" in result["error"]


def test_stream_runtime_closes_sessions_on_provider_failure(tmp_path):
    class Agent:
        config = {"working_path": str(tmp_path)}

        def Send(self, **kwargs):
            self.sid = start(self, 'import time; time.sleep(30)')
            raise RuntimeError('provider failed')

    instance = configured_fake(Agent())
    with pytest.raises(RuntimeError, match='provider failed'):
        AgentStreamRuntime(None).send(instance)
    assert instance._console_session_registry.closed
    assert all(s.done.is_set() for s in instance._console_session_registry.sessions.values())


def test_tools_exported_and_remote_execution_rejected(agent):
    import functions.system_tools as system_tools
    from src.tool.base_tool import BaseTool
    tools = BaseTool(agent)
    tools.addTool('system_tools')
    for name in ('start_console_session','read_console_session','wait_console_session','stop_console_session'):
        assert name in system_tools.__all__
        assert getattr(system_tools,name+'_declaration')['function']['name'] == name
        assert name in tools.function_map
    agent._agentpark_remote_enabled = True
    result = json.loads(start_console_session('echo should-not-run', agent=agent))
    assert result['status'] == 'invalid_arguments' and 'remote' in result['error']


def test_provider_submission_limit_preserves_all_unread_output(agent):
    agent.config['toolResultSubmissionMaxChars'] = 1200
    sid = start(agent, "print('x'*9000)")
    raw = wait_console_session(sid, wait_seconds=10, max_chars=65536, agent=agent)
    received = ''
    while True:
        assert len(raw) <= 1200
        result = json.loads(raw)
        assert result['status'] == 'success'
        received += result['stdout']
        if not result['has_more_output']:
            break
        raw = read_console_session(sid, cursor=result['next_cursor'], max_chars=65536, agent=agent)
    assert received.strip() == 'x'*9000


def test_output_limit_reports_error_and_stops_process(agent, monkeypatch):
    from functions.console_session_output import SessionOutput
    monkeypatch.setattr(SessionOutput, 'MAX_CHARS', 50)
    sid = start(agent, "import time; print('x'*1000,flush=True); time.sleep(30)")
    result = json.loads(wait_console_session(sid, wait_seconds=10, agent=agent))
    assert result['finished'] and result['status'] == 'error'
    assert 'limit' in result['error']


def test_start_failure_is_reported_and_creates_no_session(agent, monkeypatch):
    import functions.console_session_process as module

    def fail(*args, **kwargs):
        raise OSError('intentional launch failure')

    monkeypatch.setattr(module.subprocess, 'Popen', fail)
    result = json.loads(start_console_session('echo test', agent=agent))
    assert result['status'] == 'exception' and 'intentional launch failure' in result['error']
    assert not registry_for(agent).sessions


def test_wait_tool_cancellation_stops_owned_process(agent):
    from src.runtime_cancellation import tool_call_cancellation_scope
    sid = start(agent, 'import time; time.sleep(30)')
    cancel = threading.Event()
    timer = threading.Timer(.2, cancel.set)
    timer.start()
    try:
        with tool_call_cancellation_scope(cancel):
            result = json.loads(wait_console_session(sid, wait_seconds=10, agent=agent))
    finally:
        timer.cancel()
    assert result['finished'] and result['status'] == 'stopped'


def test_reusing_agent_for_next_run_gets_fresh_sessions(tmp_path):
    class Agent:
        config = {'working_path': str(tmp_path)}

        def Send(self, **kwargs):
            sid = start(self, "print('ok')")
            result = json.loads(wait_console_session(sid, wait_seconds=10, agent=self))
            assert result['status'] == 'success'
            return sid

    instance = configured_fake(Agent())
    runtime = AgentStreamRuntime(None)
    first = runtime.send(instance)
    second = runtime.send(instance)
    assert first != second
    assert first not in instance._console_session_registry.sessions


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job accounting')
def test_explicit_helper_cleanup_policy_is_reported(agent, tmp_path):
    child = "import time,pathlib; time.sleep(2); pathlib.Path('helper-leak').write_text('bad')"
    script = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
    result = json.loads(start_console_session(command(script), child_process_policy='terminate', agent=agent))
    result = json.loads(wait_console_session(result['session_id'], wait_seconds=10, agent=agent))
    assert result['status'] == 'success' and result['returncode'] == 0
    assert result['child_process_policy'] == 'terminate'
    assert result['terminated_children_on_shell_exit'] >= 1
    time.sleep(2.2)
    assert not (tmp_path/'helper-leak').exists()
