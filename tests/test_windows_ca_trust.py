"""Exercise the installer against an in-memory store, never changing Windows trust."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


TRUST = Path(__file__).resolve().parents[1] / "deploy/peer-network/client-trust"


def write_test_certificate(root: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AgentPark test CA")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    (root / "AgentPark-Root-CA.crt").write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM))
    (root / "certificate-info.json").write_text(
        json.dumps({"root_sha256": certificate.fingerprint(hashes.SHA256()).hex()}),
        encoding="utf-8")


@unittest.skipUnless(os.name == "nt", "Windows PowerShell certificate installer")
class WindowsCaTrustTests(unittest.TestCase):
    def run_installer(self, installed=False, bad_fingerprint=False):
        with tempfile.TemporaryDirectory(prefix="AgentPark CA test ") as directory:
            root = Path(directory)
            write_test_certificate(root)
            if bad_fingerprint:
                (root / "certificate-info.json").write_text(
                    json.dumps({"root_sha256": "0" * 64}), encoding="utf-8")
            source = (TRUST / "install-windows.ps1").read_text(encoding="utf-8")
            source = source.replace(
                "[System.Security.Cryptography.X509Certificates.X509Store]::new('Root', 'CurrentUser')",
                "(New-TestRootStore $certificate)")
            harness = r'''
$ErrorActionPreference = 'Stop'
function New-TestRootStore($certificate) {
    $store = [pscustomobject]@{
        Certificates = [System.Security.Cryptography.X509Certificates.X509Certificate2Collection]::new()
        Adds = 0
        Opens = [System.Collections.Generic.List[string]]::new()
        Closed = $false
    }
    if (INSTALLED) { [void]$store.Certificates.Add($certificate) }
    $store | Add-Member ScriptMethod Open { param($mode) $this.Opens.Add($mode); $this.Closed = $false }
    $store | Add-Member ScriptMethod Close { $this.Closed = $true }
    $store | Add-Member ScriptMethod Add {
        param($cert)
        if ($this.Opens[-1] -ne 'ReadWrite') { throw 'Write without writable store' }
        $this.Adds++
        [void]$this.Certificates.Add($cert)
    }
    $global:testStore = $store
    return $store
}
try {
    & {
INSTALLER
    } | Out-Null
    $global:testStore | Select-Object Adds, Opens, Closed | ConvertTo-Json -Compress
} catch {
    Write-Output $_.Exception.Message
    exit 1
}
'''.replace("INSTALLED", "$true" if installed else "$false").replace("INSTALLER", source)
            script = root / "test.ps1"
            script.write_text(harness, encoding="utf-8-sig")
            return subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                capture_output=True, text=True, timeout=30)

    def test_missing_certificate_is_installed(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "Adds": 1, "Opens": ["ReadOnly", "ReadWrite"], "Closed": True})

    def test_existing_certificate_skips_write_access(self):
        result = self.run_installer(installed=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "Adds": 0, "Opens": ["ReadOnly"], "Closed": True})

    def test_fingerprint_mismatch_is_rejected(self):
        result = self.run_installer(bad_fingerprint=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Root certificate fingerprint mismatch", result.stdout)
