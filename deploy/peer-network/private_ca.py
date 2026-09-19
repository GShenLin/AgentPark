"""Certificate profiles for the single-IP private AgentPark deployment."""
from datetime import datetime, timedelta, timezone
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

IP = ipaddress.ip_address('203.0.113.10')
PEM = serialization.Encoding.PEM


def new_key():
    return ec.generate_private_key(ec.SECP256R1())


def key_bytes(key):
    return key.private_bytes(PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def name(label):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])


def public_bytes(key):
    return key.public_key().public_bytes(serialization.Encoding.DER,
                                       serialization.PublicFormat.SubjectPublicKeyInfo)


def builder(subject, public_key, issuer, days):
    now = datetime.now(timezone.utc)
    return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
            .public_key(public_key).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=days)))


def ca_extensions(cert, key, issuer_key, path_length):
    return (cert.add_extension(x509.BasicConstraints(ca=True, path_length=path_length), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key), critical=False))


def create_root(key):
    subject = name('AgentPark Private Root CA 2026')
    cert = builder(subject, key.public_key(), subject, 3650)
    return ca_extensions(cert, key.public_key(), key.public_key(), 1).sign(key, hashes.SHA256())


def issuer_csr(key):
    return (x509.CertificateSigningRequestBuilder()
            .subject_name(name('AgentPark ECS Issuing CA 203.0.113.10'))
            .sign(key, hashes.SHA256()))


def sign_issuer(csr, root, root_key):
    if not csr.is_signature_valid or csr.subject != name('AgentPark ECS Issuing CA 203.0.113.10'):
        raise ValueError('Unexpected or invalid issuer CSR.')
    cert = ca_extensions(builder(csr.subject, csr.public_key(), root.subject, 1825),
                         csr.public_key(), root_key.public_key(), 0)
    # The online issuer may only certify this exact public IP, never DNS names.
    constraints = x509.NameConstraints([x509.IPAddress(ipaddress.ip_network(str(IP) + '/32'))],
                                      [x509.DNSName('')])
    return cert.add_extension(constraints, critical=True).sign(root_key, hashes.SHA256())


def sign_server(csr, issuer, issuer_key):
    if not csr.is_signature_valid:
        raise ValueError('Invalid server CSR signature.')
    names = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if list(names) != [x509.IPAddress(IP)]:
        raise ValueError('Server CSR must contain exactly the configured public IP.')
    now = datetime.now(timezone.utc)
    if issuer.not_valid_after_utc <= now + timedelta(days=91):
        raise ValueError('Issuing CA expires too soon; renew it using the offline root.')
    if issuer.not_valid_before_utc > now or issuer.subject != name('AgentPark ECS Issuing CA 203.0.113.10'):
        raise ValueError('Issuing CA identity or validity is invalid.')
    if public_bytes(issuer_key) != issuer.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
        raise ValueError('Issuing CA key does not match its certificate.')
    return (builder(x509.Name([]), csr.public_key(), issuer.subject, 90)
            .add_extension(names, critical=True)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(csr.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
            .sign(issuer_key, hashes.SHA256()))
