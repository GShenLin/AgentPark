param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot
)

$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath($WorkspaceRoot.Trim().Trim('"')).TrimEnd('\')
$runtimeDir = Join-Path $root '.runtime'
$logPath = Join-Path $runtimeDir ("restart-worker-{0}.log" -f $PID)
$stopScript = Join-Path $root 'scripts\restart_agentpark.ps1'
$buildScript = Join-Path $root 'build_and_run.bat'

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

try {
    Set-Content -LiteralPath $logPath -Encoding Unicode -Value "===== restart worker $(Get-Date -Format o) PID=$PID ====="
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript -WorkspaceRoot $root *>> $logPath
    $stopExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($stopExitCode -ne 0) {
        throw "Stop phase failed with exit code $stopExitCode."
    }
    $env:AGENTPARK_NO_PAUSE = '1'
    Add-Content -LiteralPath $logPath -Encoding Unicode -Value '[INFO] Starting canonical build_and_run.bat.'
    $ErrorActionPreference = 'Continue'
    & $buildScript
    $buildExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    exit $buildExitCode
} catch {
    Add-Content -LiteralPath $logPath -Encoding Unicode -Value "[ERROR] $($_.Exception.Message)"
    exit 1
}
