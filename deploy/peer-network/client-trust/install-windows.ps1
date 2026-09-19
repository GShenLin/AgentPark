$ErrorActionPreference = 'Stop'
$metadata = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'certificate-info.json') -Raw | ConvertFrom-Json
$path = Join-Path $PSScriptRoot 'AgentPark-Root-CA.crt'
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($path)
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $actual = ([System.BitConverter]::ToString($sha256.ComputeHash($certificate.RawData))).Replace('-', '').ToLowerInvariant()
} finally {
    $sha256.Dispose()
}
if ($actual -ne $metadata.root_sha256) { throw 'Root certificate fingerprint mismatch.' }
$store = [System.Security.Cryptography.X509Certificates.X509Store]::new('Root', 'CurrentUser')
try {
    $store.Open('ReadWrite')
    $store.Add($certificate)
    if ($store.Certificates.Find('FindByThumbprint', $certificate.Thumbprint, $false).Count -ne 1) {
        throw 'Root certificate trust was not installed.'
    }
} finally { $store.Close() }
Write-Output 'AgentPark private CA is trusted by the current Windows user.'
