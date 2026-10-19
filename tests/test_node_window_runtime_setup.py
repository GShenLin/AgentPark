"""Exercise the Windows startup installer without network or the real node_modules."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ensure_node_window_runtime.ps1'
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows desktop runtime setup')


@pytest.mark.parametrize('scenario,success,installs', [
    ('installed', True, False),
    ('missing', True, True),
    ('old_binary', True, True),
    ('missing_executable', True, True),
    ('npm_failure', False, True),
    ('incomplete_install', False, True),
])
def test_runtime_installation_is_verified_and_only_runs_when_needed(tmp_path, scenario, success, installs):
    root = tmp_path / 'workspace with spaces'
    host = root / 'desktop/node-window'
    host.mkdir(parents=True)
    (host / 'package.json').write_text(json.dumps({'devDependencies': {'electron': '44.7.0'}}))
    electron = host / 'node_modules/electron'
    if scenario in {'installed', 'old_binary', 'missing_executable'}:
        (electron / 'dist').mkdir(parents=True)
        (electron / 'package.json').write_text('{"version":"44.7.0"}')
        (electron / 'path.txt').write_text('electron.exe')
        (electron / 'dist/version').write_text('44.6.0' if scenario == 'old_binary' else '44.7.0')
        if scenario != 'missing_executable':
            (electron / 'dist/electron.exe').touch()
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    installer = binaries / 'fake_install.py'
    installer.write_text('''import json, os, pathlib, sys
host = pathlib.Path(sys.argv[3])
(host / 'npm-args.json').write_text(json.dumps(sys.argv[1:]))
scenario = os.environ['RUNTIME_TEST_SCENARIO']
if scenario == 'npm_failure': sys.exit(17)
if scenario == 'incomplete_install': sys.exit(0)
electron = host / 'node_modules/electron'
(electron / 'dist').mkdir(parents=True, exist_ok=True)
(electron / 'package.json').write_text('{"version":"44.7.0"}')
(electron / 'path.txt').write_text('electron.exe')
(electron / 'dist/version').write_text('44.7.0')
(electron / 'dist/electron.exe').touch()
''', encoding='utf-8')
    (binaries / 'npm.cmd').write_text(
        f'@echo off\n"{sys.executable}" "{installer}" %*\nexit /b %errorlevel%\n', encoding='utf-8')
    env = {**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
           'RUNTIME_TEST_SCENARIO': scenario, 'NODE_ENV': 'production', 'npm_config_ignore_scripts': 'true'}
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(SCRIPT), '-WorkspaceRoot', str(root)],
                            env=env, capture_output=True, timeout=15)
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    invocation = host / 'npm-args.json'
    assert invocation.exists() is installs
    if installs:
        assert json.loads(invocation.read_text()) == ['ci', '--prefix', str(host), '--include=dev', '--include=optional',
                                                      '--ignore-scripts=false', '--no-audit']
