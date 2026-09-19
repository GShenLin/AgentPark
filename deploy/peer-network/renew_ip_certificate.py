"""Issue/renew the ECS IP certificate using a Windows user's working network."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import josepy
import requests
from acme import challenges, client, messages
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tls_workbench import INSTANCE, ensure_daemon, protect, remote, run

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.auth' / 'acme'
RUNTIME = ROOT / '.runtime' / 'acme'
IP = '203.0.113.10'


def atomic_json(path: Path, data: dict):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def valid_candidate(pem: bytes, csr) -> bool:
    cert = x509.load_pem_x509_certificate(pem)
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if list(names) != [x509.IPAddress(ipaddress.ip_address(IP))]:
        raise ValueError('Certificate IP does not match this deployment.')
    encoding = serialization.Encoding.DER
    form = serialization.PublicFormat.SubjectPublicKeyInfo
    if cert.public_key().public_bytes(encoding, form) != csr.public_key().public_bytes(encoding, form):
        raise ValueError('Certificate does not match the current ECS CSR.')
    now = datetime.now(timezone.utc)
    return cert.not_valid_before_utc <= now and cert.not_valid_after_utc > now + timedelta(days=3)


def make_client(staging: bool):
    name = 'staging' if staging else 'production'
    path = STATE / f'account-{name}.dpapi'
    if path.exists():
        account = json.loads(protect(path.read_bytes(), decrypt=True))
        key = josepy.JWKRSA.json_loads(account['key'])
    else:
        key = josepy.JWKRSA(key=rsa.generate_private_key(public_exponent=65537, key_size=2048))
        account = {'key': key.json_dumps(), 'registration': None}
    network = client.ClientNetwork(key, user_agent='AgentPark-ECS-Certificate/1', timeout=30)
    network.session.trust_env = False
    directory_url = f"https://{'acme-staging-v02' if staging else 'acme-v02'}.api.letsencrypt.org/directory"
    acme = client.ClientV2(client.ClientV2.get_directory(directory_url, network), network)
    if account['registration']:
        network.account = messages.RegistrationResource.json_loads(account['registration'])
    else:
        registration = acme.new_account(messages.NewRegistration.from_data(terms_of_service_agreed=True))
        account['registration'] = registration.json_dumps()
        path.write_bytes(protect(json.dumps(account).encode()))
    return acme, key


def issue(csr_pem: bytes, staging: bool) -> bytes:
    acme, key = make_client(staging)
    order = acme.new_order(csr_pem, profile='shortlived')
    published = []
    try:
        for authorization in order.authorizations:
            if authorization.body.status == messages.STATUS_VALID:
                continue
            challenge = next(c for c in authorization.body.challenges if isinstance(c.chall, challenges.HTTP01))
            response, validation = challenge.response_and_validation(key)
            token = challenge.chall.encode('token')
            published.append(token)
            remote('publish', '--token', token, '--validation', validation)
            with requests.Session() as session:
                session.trust_env = False
                proof = session.get(f'http://{IP}/.well-known/acme-challenge/{token}', timeout=15)
            proof.raise_for_status()
            if proof.text != validation:
                raise ValueError('Public HTTP-01 challenge content does not match.')
            acme.answer_challenge(challenge, response)
        result = acme.poll_and_finalize(order, deadline=datetime.now() + timedelta(minutes=2))
        return result.fullchain_pem.encode('ascii')
    finally:
        for token in published:
            remote('clean', '--token', token)


def main(staging: bool):
    if (ROOT / '.auth' / 'private-ca' / 'root.pem').exists():
        raise RuntimeError('This deployment uses a private CA. Public ACME renewal is disabled.')
    STATE.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    ensure_daemon()
    info = json.loads(remote('info'))
    csr_pem = info['csr'].encode('ascii')
    csr = x509.load_pem_x509_csr(csr_pem)
    if not csr.is_signature_valid or list(csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value) != [x509.IPAddress(ipaddress.ip_address(IP))]:
        raise ValueError('ECS CSR is invalid or covers an unexpected IP.')
    if not staging and info['certificate'] and valid_candidate(info['certificate'].encode(), csr):
        cert = x509.load_pem_x509_certificate(info['certificate'].encode())
        return {'ok': True, 'action': 'not_due', 'expires_at': cert.not_valid_after_utc.isoformat()}
    cache = RUNTIME / ('staging-fullchain.pem' if staging else 'fullchain.pem')
    if cache.exists() and valid_candidate(cache.read_bytes(), csr):
        pem = cache.read_bytes()
    else:
        pem = issue(csr_pem, staging)
        cache.write_bytes(pem)
    cert = x509.load_pem_x509_certificate(pem)
    if staging:
        return {'ok': True, 'action': 'staging_validated', 'expires_at': cert.not_valid_after_utc.isoformat()}
    run('upload', str(cache), '/var/lib/agentpark-tls/incoming.pem', '-i', INSTANCE, '-f')
    result = json.loads(remote('install'))
    return {'ok': True, 'action': 'renewed', **result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--staging', action='store_true')
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    try:
        status = main(args.staging)
    except Exception as exc:
        status = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    status['checked_at'] = datetime.now(timezone.utc).isoformat()
    atomic_json(RUNTIME / ('staging-status.json' if args.staging else 'renewal-status.json'), status)
    if sys.stdout is not None:
        print(json.dumps(status, ensure_ascii=False))
    sys.exit(0 if status['ok'] else 1)
