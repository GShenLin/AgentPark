"""A real GUI-subsystem executable verifies PowerShell's asynchronous launch edge."""

import json
import os
import time
from types import SimpleNamespace

import pytest

from functions.console_tools import execute_console_command
from functions.console_session_registry import console_session_scope
from functions.console_session_tools import start_console_session, wait_console_session


@pytest.mark.skipif(os.name != 'nt', reason='Windows GUI process semantics')
def test_gui_program_requires_foreground_wait_and_preserves_exit_code(tmp_path):
    program = tmp_path / 'gui-probe.exe'
    marker = tmp_path / 'finished.txt'
    source = ('using System; using System.IO; using System.Threading; '
              'public class Probe { public static void Main(string[] args) { '
              'Thread.Sleep(1500); File.WriteAllText(args[0], "done"); Environment.Exit(7); } }')
    agent = SimpleNamespace(config={'working_path': str(tmp_path)})
    compile_result = json.loads(execute_console_command(
        f"Add-Type -TypeDefinition '{source}' -OutputAssembly '{program}' -OutputType WindowsApplication",
        agent=agent,
    ))
    assert compile_result['status'] == 'success', compile_result
    with console_session_scope(agent):
        invocation = f"& '{program}' '{marker}'"
        first = json.loads(start_console_session(invocation, agent=agent))
        result = json.loads(wait_console_session(first['session_id'], wait_seconds=10, agent=agent))
        assert result['status'] == 'error' and 'child processes' in result['error'], result
        time.sleep(1.7)
        assert not marker.exists()
        second = json.loads(start_console_session(invocation + ' | Out-Default', agent=agent))
        result = json.loads(wait_console_session(second['session_id'], wait_seconds=10, agent=agent))
        assert result['returncode'] == 7 and result['status'] == 'error', result
        assert 'error' not in result  # Native non-zero exit, not lifecycle failure.
        assert marker.read_text() == 'done'
