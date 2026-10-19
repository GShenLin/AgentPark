import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
import uuid

ROOT = Path('/opt/agentpark-coordinator')
DEST = ROOT / 'webui/dist'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def install(source, target):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = target.with_name(target.name + '.frontend-stage')
    shutil.copyfile(source, temporary)
    temporary.chmod(0o644)
    os.replace(temporary, target)

def restore(backup):
    if backup.parent != ROOT / 'backups' or not backup.name.startswith('frontend-'):
        raise RuntimeError('Unexpected backup path')
    if not (backup / 'index.html').is_file():
        raise RuntimeError('Backup entry point is missing')
    for path in sorted(backup.rglob('*'), key=lambda p: p.name == 'index.html'):
        if path.is_file():
            install(path, DEST / path.relative_to(backup))

def publish():
    archive = Path(sys.argv[1])
    if digest(archive) != sys.argv[2]:
        raise RuntimeError('Upload checksum mismatch')
    if digest(DEST / 'index.html') != sys.argv[3]:
        raise RuntimeError('Live frontend changed since preflight')
    env = {}
    for line in Path('/etc/agentpark/signaling.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key == 'AGENTPARK_PORTAL_WEB_ROOT':
            env[key] = value.strip().strip('\"\'')
    if Path(env['AGENTPARK_PORTAL_WEB_ROOT']).resolve() != DEST.resolve():
        raise RuntimeError('Unexpected live frontend directory')

    with tempfile.TemporaryDirectory(prefix='frontend-stage-', dir=ROOT / 'webui') as temporary:
        stage = Path(temporary)
        with tarfile.open(archive, 'r:gz') as bundle:
            for member in bundle.getmembers():
                name = PurePosixPath(member.name)
                if not member.isfile() or name.is_absolute() or '..' in name.parts:
                    raise RuntimeError('Invalid archive member')
                target = stage.joinpath(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.extractfile(member).read())
        manifest = json.loads((stage / 'manifest.json').read_text())
        for name, expected in manifest.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise RuntimeError('Invalid manifest path')
            if digest(stage / 'dist' / name) != expected:
                raise RuntimeError('Staged hash mismatch: ' + name)
        if not {'index.html', 'portal-sw.js'} <= manifest.keys():
            raise RuntimeError('Required entry files missing')
        if all((DEST / name).is_file() and digest(DEST / name) == expected for name, expected in manifest.items()):
            print(json.dumps({'status': 'installed', 'unchanged': True, 'files_verified': len(manifest), 'backup': None}))
            return
        backup = ROOT / 'backups' / ('frontend-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
        shutil.copytree(DEST, backup)
        try:
            # Entry point last; retain earlier fingerprinted assets for existing sessions.
            for name in sorted(manifest, key=lambda name: name == 'index.html'):
                install(stage / 'dist' / name, DEST / name)
            for name, expected in manifest.items():
                if digest(DEST / name) != expected:
                    raise RuntimeError('Installed hash mismatch: ' + name)
        except BaseException:
            restore(backup)
            raise
        print(json.dumps({'status': 'installed', 'files_verified': len(manifest), 'backup': str(backup)}))

if __name__ == '__main__':
    import fcntl
    # A second launcher must not interleave asset writes with an ongoing release.
    with (ROOT / 'webui' / '.frontend-deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        publish()
    # Only remove the two uniquely named temporary files uploaded for this run.
    script = Path(__file__).resolve()
    archive = Path(sys.argv[1]).resolve()
    if (script.parent == archive.parent == Path('/tmp')
            and script.stem == archive.name.removesuffix('.tar.gz')
            and script.name.startswith('agentpark-frontend-')):
        archive.unlink()
        script.unlink()
