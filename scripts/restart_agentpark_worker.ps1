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
$env:AGENTPARK_NO_PAUSE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
. (Join-Path $PSScriptRoot 'restart_guard.ps1')
$restartGuard = Open-RestartGuard $runtimeDir
if ($null -eq $restartGuard) {
    Write-Host '[INFO] Restart already in progress for this workspace; duplicate request ignored.'
    exit 0
}

Set-Content -LiteralPath $logPath -Encoding UTF8 -Value "===== restart worker $(Get-Date -Format o) PID=$PID ====="

function Write-RestartLog([string]$Message) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value $Message
    Write-Host $Message
}

function Invoke-LoggedCommand([string]$Executable, [string[]]$CommandArguments) {
    $null = Get-Command $Executable -ErrorAction Stop
    # Windows PowerShell wraps native stderr in ErrorRecords. Keep the transcript
    # and judge the command by its exit code, including all build diagnostics.
    $ErrorActionPreference = 'Continue'
    & $Executable @CommandArguments 2>&1 | ForEach-Object {
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ([string]$_) -ErrorAction Stop
        Write-Host ([string]$_)
    }
    return $LASTEXITCODE
}

try {
    Write-RestartLog '[INFO] Stopping previous workspace processes.'
    $stopExit = Invoke-LoggedCommand 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $stopScript, '-WorkspaceRoot', $root)
    if ($stopExit -ne 0) { throw "Stop phase failed with exit code $stopExit." }
    Write-RestartLog '[INFO] Starting build_and_run.bat, which owns startup repair and retries.'
    $env:AGENTPARK_STARTUP_LOG = Join-Path $runtimeDir ("restart-build-{0}.log" -f $PID)
    Write-RestartLog "Build transcript: $env:AGENTPARK_STARTUP_LOG"
    # Keep the long-lived CLI's console handles outside the worker's logging pipe.
    $readyPath = Join-Path $runtimeDir ("restart-ready-{0}" -f $PID)
    if (Test-Path -LiteralPath $readyPath) { Remove-Item -LiteralPath $readyPath }
    $env:AGENTPARK_STARTUP_READY_FILE = $readyPath
    $buildProcess = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/s', '/c', ('""{0}""' -f $buildScript)) -WorkingDirectory $root -WindowStyle Hidden -PassThru
    while (-not $buildProcess.WaitForExit(250)) {
        if (Test-Path -LiteralPath $readyPath) {
            Write-RestartLog '[INFO] Server readiness confirmed; restart completed.'
            exit 0
        }
    }
    $buildProcess.WaitForExit()
    $buildExit = $buildProcess.ExitCode
    if ($buildExit -eq 0) { exit 0 }
    if (Test-Path -LiteralPath $env:AGENTPARK_STARTUP_LOG -PathType Leaf) {
        Get-Content -LiteralPath $env:AGENTPARK_STARTUP_LOG -Encoding UTF8 |
            Add-Content -LiteralPath $logPath -Encoding UTF8
    }
    throw "build_and_run.bat failed with exit code $buildExit."
} catch {
    Write-RestartLog "[ERROR] $($_.Exception.Message) Inspect $logPath"
    exit 1
} finally {
    $restartGuard.Dispose()
}
