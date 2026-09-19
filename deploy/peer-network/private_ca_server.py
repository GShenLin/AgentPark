"""Root-only ECS issuer bootstrap and autonomous private TLS renewal."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from private_ca import PEM, issuer_csr, key_bytes, new_key, sign_server
from tls_server import ROOT, atomic_write, install

CA = ROOT / 'private-ca'


def prepare():
    CA.mkdir(mode=0o700, exist_ok=True)
    path = CA / 'issuer-key.pem'
    if not path.exists():
        atomic_write(path, key_bytes(new_key()))
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    atomic_write(CA / 'issuer.csr', issuer_csr(key).public_bytes(PEM))
    print(json.dumps({'prepared': True}))


def renew(stage_only=False):
    now = datetime.now(timezone.utc)
    issuer = x509.load_pem_x509_certificate((CA / 'issuer.pem').read_bytes())
    current = x509.load_pem_x509_certificate((ROOT / 'fullchain.pem').read_bytes())
    if not stage_only and current.issuer == issuer.subject and current.not_valid_after_utc > now + timedelta(days=30):
        # Surface the required offline issuer renewal well before it can stop leaf renewal.
        if issuer.not_valid_after_utc <= now + timedelta(days=120):
            raise ValueError('Private issuing CA needs renewal using the offline root within 30 days.')
        result = {'action': 'not_due', 'expires_at': current.not_valid_after_utc.isoformat()}
    else:
        key = serialization.load_pem_private_key((CA / 'issuer-key.pem').read_bytes(), password=None)
        csr = x509.load_pem_x509_csr((ROOT / 'server.csr').read_bytes())
        cert = sign_server(csr, issuer, key)
        atomic_write(ROOT / 'incoming.pem', cert.public_bytes(PEM) + issuer.public_bytes(PEM))
        if not stage_only:
            install(CA / 'root.pem')
        result = {'action': 'staged' if stage_only else 'renewed', 'expires_at': cert.not_valid_after_utc.isoformat()}
    result.update(ok=True, checked_at=now.isoformat())
    atomic_write(CA / 'renewal-status.json', json.dumps(result).encode())
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'stage', 'renew', 'activate'])
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare()
    elif args.operation == 'activate':
        install(CA / 'root.pem')
    else:
        renew(stage_only=args.operation == 'stage')
