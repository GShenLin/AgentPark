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
$repairScript = Join-Path $root 'scripts\repair_startup.bat'
$maxRepairs = 3
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
for ($attempt = 0; $attempt -le $maxRepairs; $attempt++) {
    try {
        Write-RestartLog "[INFO] Startup attempt $($attempt + 1): stopping previous workspace processes."
        $stopExit = Invoke-LoggedCommand 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $stopScript, '-WorkspaceRoot', $root)
        if ($stopExit -ne 0) { throw "Stop phase failed with exit code $stopExit." }
        Write-RestartLog '[INFO] Starting canonical build_and_run.bat; readiness is checked before Companion CLI starts.'
        $env:AGENTPARK_STARTUP_LOG = Join-Path $runtimeDir ("restart-build-{0}-{1}.log" -f $PID, ($attempt + 1))
        Write-RestartLog "[INFO] Build transcript: $env:AGENTPARK_STARTUP_LOG"
        # Do not pipe the long-lived CLI: prompt_toolkit requires console handles.
        $readyPath = Join-Path $runtimeDir ("restart-ready-{0}-{1}" -f $PID, $attempt)
        if (Test-Path -LiteralPath $readyPath) { Remove-Item -LiteralPath $readyPath }
        $env:AGENTPARK_STARTUP_READY_FILE = $readyPath
        $buildProcess = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/s', '/c', ('""{0}""' -f $buildScript)) -WorkingDirectory $root -WindowStyle Hidden -PassThru
        while (-not $buildProcess.WaitForExit(250)) {
            if (Test-Path -LiteralPath $readyPath) {
                # The launcher and CLI must outlive this worker, but the restart
                # lock covers only startup. Future restart clicks remain usable.
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
        Write-RestartLog "[ERROR] $($_.Exception.Message)"
    }
    if ($attempt -eq $maxRepairs) {
        Write-RestartLog "[ERROR] Startup still failed after $maxRepairs Companion repairs. Inspect $logPath"
        exit 1
    }
    try {
        Write-RestartLog '[INFO] Starting standalone Companion diagnosis and repair (web server not required).'
        $repairExit = Invoke-LoggedCommand $repairScript @($logPath)
        if ($repairExit -ne 0) { throw "Companion repair failed with exit code $repairExit." }
        Write-RestartLog '[INFO] Companion repair completed; rerunning build_and_run.bat to verify recovery.'
    } catch {
        Write-RestartLog "[ERROR] $($_.Exception.Message) Recovery stopped; inspect $logPath"
        exit 1
    }
}
} finally {
    $restartGuard.Dispose()
}
