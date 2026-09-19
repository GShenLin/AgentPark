"""Offline Windows root signing. Only public certificates leave this computer."""
import argparse
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from private_ca import PEM, create_root, key_bytes, new_key, sign_issuer
from tls_workbench import protect

WORKSPACE = Path(__file__).resolve().parents[2]
STATE = WORKSPACE / '.auth' / 'private-ca'
PUBLIC = Path(__file__).resolve().parent / 'client-trust'


def main(csr_path):
    STATE.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(exist_ok=True)
    key_path, root_path = STATE / 'root-key.dpapi', STATE / 'root.pem'
    if key_path.exists() != root_path.exists():
        raise ValueError('Incomplete private root state; do not overwrite it.')
    if not key_path.exists():
        key = new_key()
        root = create_root(key)
        key_path.write_bytes(protect(key_bytes(key)))
        root_path.write_bytes(root.public_bytes(PEM))
    else:
        key = serialization.load_pem_private_key(protect(key_path.read_bytes(), decrypt=True), password=None)
        root = x509.load_pem_x509_certificate(root_path.read_bytes())
    csr = x509.load_pem_x509_csr(csr_path.read_bytes())
    issuer = sign_issuer(csr, root, key)
    (STATE / 'issuer.pem').write_bytes(issuer.public_bytes(PEM))
    (PUBLIC / 'AgentPark-Root-CA.crt').write_bytes(root.public_bytes(PEM))
    metadata = {'server_ip': '203.0.113.10', 'root_sha256': root.fingerprint(hashes.SHA256()).hex(),
                'root_expires_at': root.not_valid_after_utc.isoformat(),
                'issuer_expires_at': issuer.not_valid_after_utc.isoformat()}
    (PUBLIC / 'certificate-info.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(metadata))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('issuer_csr', type=Path)
    main(parser.parse_args().issuer_csr)
