param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$nodeWindowRoot = Join-Path ([System.IO.Path]::GetFullPath($WorkspaceRoot)) 'desktop\node-window'
$manifest = Get-Content -LiteralPath (Join-Path $nodeWindowRoot 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedVersion = [string]$manifest.devDependencies.electron
if ($expectedVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw 'The node window Electron dependency must use an exact version.'
}
$electronRoot = Join-Path $nodeWindowRoot 'node_modules\electron'

function Test-NodeWindowRuntime {
    foreach ($relative in @('package.json', 'dist\version', 'dist\electron.exe', 'path.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $electronRoot $relative) -PathType Leaf)) { return $false }
    }
    $installed = Get-Content -LiteralPath (Join-Path $electronRoot 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $binaryVersion = (Get-Content -LiteralPath (Join-Path $electronRoot 'dist\version') -Raw -Encoding UTF8).Trim().TrimStart('v')
    $entryPath = (Get-Content -LiteralPath (Join-Path $electronRoot 'path.txt') -Raw -Encoding UTF8).Trim()
    return $installed.version -eq $expectedVersion -and $binaryVersion -eq $expectedVersion -and $entryPath -eq 'electron.exe'
}

if (Test-NodeWindowRuntime) {
    Write-Host "[INFO] Node window runtime already ready: Electron $expectedVersion"
    exit 0
}

Write-Host "[INFO] Installing node window runtime: Electron $expectedVersion"
# Include dev dependencies and run Electron's download hook even under production
# npm settings. npm uses the checked-in lockfile and its existing download config.
& npm.cmd ci --prefix $nodeWindowRoot --include=dev --include=optional --ignore-scripts=false --no-audit
if ($LASTEXITCODE -ne 0) {
    throw "Node window runtime installation failed (npm exit code $LASTEXITCODE)."
}
if (-not (Test-NodeWindowRuntime)) {
    throw 'npm completed but the expected Electron runtime is missing or has the wrong version.'
}
Write-Host "[INFO] Node window runtime ready: Electron $expectedVersion"
