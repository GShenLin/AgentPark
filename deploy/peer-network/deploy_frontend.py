"""Publish the built portal frontend once; the launcher treats failure as optional."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

from tls_workbench import INSTANCE, REMOTE_PYTHON, WORKBENCH

ROOT = Path(__file__).resolve().parents[2]
REMOTE_DIST = '/opt/agentpark-coordinator/webui/dist'
TOTAL_TIMEOUT = 90


def package(dist: Path, archive: Path) -> str:
    if not (dist / 'index.html').is_file() or not (dist / 'portal-sw.js').is_file():
        raise RuntimeError('Built frontend is missing; run the WebUI build first.')
    manifest = {p.relative_to(dist).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(dist.rglob('*')) if p.is_file()}
    with tarfile.open(archive, 'w:gz') as bundle:
        for name in manifest:
            bundle.add(dist / name, arcname='dist/' + name, recursive=False)
        content = json.dumps(manifest).encode('utf-8')
        entry = tarfile.TarInfo('manifest.json')
        entry.size = len(content)
        bundle.addfile(entry, io.BytesIO(content))
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def deploy(log):
    executable = shutil.which('workbench') or (str(WORKBENCH) if WORKBENCH.is_file() else None)
    if executable is None:
        raise RuntimeError('Workbench CLI is not installed. Cloud frontend was not deployed.')
    deadline = time.monotonic() + TOTAL_TIMEOUT

    def run(*args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Cloud deployment exceeded its 90-second time budget.')
        print('[INFO] Workbench ' + args[0], file=log, flush=True)
        result = subprocess.run([executable, *args], stdin=subprocess.DEVNULL, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=remaining,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout, result.stderr, file=log, flush=True)
        if result.returncode:
            raise RuntimeError(f'Workbench {args[0]} failed with exit code {result.returncode}.')
        return result.stdout.strip()

    release = uuid.uuid4().hex
    directory = ROOT / '.runtime' / 'frontend-deploy' / release
    directory.mkdir(parents=True)
    archive = directory / 'frontend.tar.gz'
    checksum = package(ROOT / 'webui' / 'dist', archive)
    remote_archive = f'/tmp/agentpark-frontend-{release}.tar.gz'
    remote_installer = f'/tmp/agentpark-frontend-{release}.py'
    before = run('exec', '--instance-id', INSTANCE, '--timeout', '20', '--command',
                 f'sha256sum {REMOTE_DIST}/index.html').split()[0]
    if len(before) != 64 or any(c not in '0123456789abcdef' for c in before):
        raise RuntimeError('Remote deployment did not return the current frontend identity.')
    run('upload', str(archive), remote_archive, '--instance-id', INSTANCE, '--force')
    run('upload', str(Path(__file__).with_name('install_frontend.py')), remote_installer,
        '--instance-id', INSTANCE, '--force')
    installed = run('exec', '--instance-id', INSTANCE, '--timeout', '45', '--command',
                    shlex.join([REMOTE_PYTHON, remote_installer, remote_archive, checksum, before]))
    receipt = json.loads(installed)
    if receipt.get('status') != 'installed':
        raise RuntimeError('Remote installer did not report a completed deployment.')
    (directory / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if receipt.get('unchanged') is True:
        print(f'[INFO] Cloud frontend already matches this build on {INSTANCE}.', flush=True)
    else:
        print(f'[INFO] Cloud frontend deployed to {INSTANCE}; backup: {receipt["backup"]}', flush=True)


def main() -> int:
    directory = ROOT / '.runtime' / 'frontend-deploy'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'latest.log').open('w', encoding='utf-8') as log:
        try:
            deploy(log)
            return 0
        except (OSError, RuntimeError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            message = f'[WARN] Cloud frontend deployment failed: {exc}'
            print(message, file=log, flush=True)
            print(message, flush=True)
            return 1


if __name__ == '__main__':
    sys.exit(main())
