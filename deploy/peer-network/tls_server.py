"""Root-only ECS certificate operations; the server private key never leaves ECS."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

ROOT = Path('/var/lib/agentpark-tls')
CHALLENGES = Path('/usr/share/nginx/html/.well-known/acme-challenge')
SERVER_IP = ipaddress.ip_address('203.0.113.10')


def atomic_write(path: Path, data: bytes, mode=0o600):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, mode)
        handle.write(data)
    os.replace(temporary, path)


def install(ca_file: Path | None = None):
    candidate = (ROOT / 'incoming.pem').read_bytes()
    certs = x509.load_pem_x509_certificates(candidate)
    leaf = certs[0]
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if list(names) != [x509.IPAddress(SERVER_IP)]:
        raise ValueError('Certificate must cover exactly the configured server IP.')
    now = datetime.now(timezone.utc)
    if not leaf.not_valid_before_utc <= now < leaf.not_valid_after_utc:
        raise ValueError('Certificate is not currently valid.')
    key = serialization.load_pem_private_key((ROOT / 'server-key.pem').read_bytes(), password=None)
    if leaf.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
        raise ValueError('Certificate does not match the ECS private key.')
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        directory = Path(temporary)
        (directory / 'leaf.pem').write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        (directory / 'chain.pem').write_bytes(b''.join(c.public_bytes(serialization.Encoding.PEM) for c in certs[1:]))
        trust = ['-CAfile', str(ca_file)] if ca_file else []
        subprocess.run(['openssl', 'verify', *trust, '-purpose', 'sslserver', '-verify_ip', str(SERVER_IP),
                        '-untrusted', str(directory / 'chain.pem'), str(directory / 'leaf.pem')], check=True, capture_output=True)
    target = ROOT / 'fullchain.pem'
    previous = target.read_bytes() if target.exists() else None
    atomic_write(target, candidate)
    try:
        subprocess.run(['nginx', '-t'], check=True, capture_output=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True, capture_output=True)
    except Exception:
        if previous is not None:
            atomic_write(target, previous)
        else:
            target.unlink()
        raise
    (ROOT / 'incoming.pem').unlink()
    print(json.dumps({'installed': True, 'expires_at': leaf.not_valid_after_utc.isoformat()}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['info', 'publish', 'clean', 'install'])
    parser.add_argument('--token')
    parser.add_argument('--validation')
    args = parser.parse_args()
    if args.operation == 'info':
        path = ROOT / 'fullchain.pem'
        print(json.dumps({'csr': (ROOT / 'server.csr').read_text(), 'certificate': path.read_text() if path.exists() else None}))
    elif args.operation == 'install':
        install()
    else:
        if not args.token or not re.fullmatch(r'[A-Za-z0-9_-]{20,200}', args.token):
            raise ValueError('Invalid HTTP-01 challenge token.')
        path = CHALLENGES / args.token
        if args.operation == 'publish':
            if not args.validation or not re.fullmatch(re.escape(args.token) + r'\.[A-Za-z0-9_-]{43}', args.validation):
                raise ValueError('Invalid HTTP-01 validation response.')
            atomic_write(path, args.validation.encode('ascii'), 0o644)
        else:
            path.unlink(missing_ok=True)
        print(json.dumps({'ok': True}))


if __name__ == '__main__':
    main()
