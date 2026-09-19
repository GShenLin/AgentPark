"""Security boundaries of the offline root and the single-IP online issuer."""
import importlib.util
import ipaddress
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes

spec = importlib.util.spec_from_file_location('deployment_private_ca',
    Path(__file__).parents[1] / 'deploy' / 'peer-network' / 'private_ca.py')
pki = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pki)


def chain():
    root_key, issuer_key = pki.new_key(), pki.new_key()
    root = pki.create_root(root_key)
    issuer = pki.sign_issuer(pki.issuer_csr(issuer_key), root, root_key)
    return root, issuer, issuer_key


def csr(*names):
    return (x509.CertificateSigningRequestBuilder().subject_name(pki.name('test'))
            .add_extension(x509.SubjectAlternativeName(list(names)), critical=False)
            .sign(pki.new_key(), hashes.SHA256()))


def test_online_issuer_cannot_create_subordinate_ca_or_other_ip():
    root, issuer, key = chain()
    assert issuer.extensions.get_extension_for_class(x509.BasicConstraints).value.path_length == 0
    constraints = issuer.extensions.get_extension_for_class(x509.NameConstraints)
    assert constraints.critical
    assert constraints.value.permitted_subtrees == [x509.IPAddress(ipaddress.ip_network('203.0.113.10/32'))]
    assert constraints.value.excluded_subtrees == [x509.DNSName('')]
    issuer.verify_directly_issued_by(root)
    for names in [(x509.IPAddress(ipaddress.ip_address('47.109.29.76')),),
                  (x509.DNSName('203.0.113.10'),),
                  (x509.IPAddress(pki.IP), x509.DNSName('example.com'))]:
        with pytest.raises(ValueError, match='exactly'):
            pki.sign_server(csr(*names), issuer, key)


def test_leaf_identity_purpose_and_validity():
    _, issuer, key = chain()
    leaf = pki.sign_server(csr(x509.IPAddress(pki.IP)), issuer, key)
    leaf.verify_directly_issued_by(issuer)
    assert not leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert list(leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) == [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]
    assert 90 <= (leaf.not_valid_after_utc - leaf.not_valid_before_utc).total_seconds() / 86400 < 91
    with pytest.raises(ValueError, match='does not match'):
        pki.sign_server(csr(x509.IPAddress(pki.IP)), issuer, pki.new_key())
