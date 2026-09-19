param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot
)

$ErrorActionPreference = 'Stop'

function Get-ConfiguredServerPort {
    param([Parameter(Mandatory = $true)][string]$Root)
    $configPath = Join-Path $Root 'config\config.json'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return 8766
    }
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $port = if ($null -ne $config.server -and $null -ne $config.server.port) { [int]$config.server.port } else { 8766 }
    if ($port -le 0 -or $port -gt 65535) {
        throw 'config/config.json field server.port must be between 1 and 65535.'
    }
    return $port
}

$root = [System.IO.Path]::GetFullPath($WorkspaceRoot.Trim().Trim('"')).TrimEnd('\')
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Workspace root does not exist: $root"
}
$workerPath = Join-Path $root 'scripts\restart_agentpark_worker.ps1'
. (Join-Path $PSScriptRoot 'restart_guard.ps1')
if (Test-RestartInProgress (Join-Path $root '.runtime')) {
    Write-Host '[INFO] Restart already in progress for this workspace; using the existing restart.'
    exit 0
}
if (-not (Test-Path -LiteralPath $workerPath -PathType Leaf)) {
    throw "Restart worker does not exist: $workerPath"
}

$powershellPath = Join-Path $PSHOME 'powershell.exe'
$commandLine = (
    '"{0}" -NoProfile -ExecutionPolicy Bypass -File "{1}" -WorkspaceRoot "{2}"' -f
    $powershellPath,
    $workerPath.Replace('"', '\"'),
    $root.Replace('"', '\"')
)

$port = Get-ConfiguredServerPort -Root $root
$originalServerPids = @(
    Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
$processStartup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{
    ShowWindow = [uint16]0
}
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $commandLine
    CurrentDirectory = $root
    ProcessStartupInformation = $processStartup
}
if ([int]$created.ReturnValue -ne 0 -or [int]$created.ProcessId -le 0) {
    throw "Windows failed to create the independent restart worker: return_value=$($created.ReturnValue)"
}

$workerPid = [int]$created.ProcessId
Write-Host "[INFO] Independent restart worker started: PID $workerPid"
if ($originalServerPids.Count -eq 0) {
    exit 0
}

$deadline = (Get-Date).AddSeconds(45)
do {
    $currentListeners = @(
        Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
    $oldListeners = @($originalServerPids | Where-Object { $currentListeners -contains $_ })
    if ($oldListeners.Count -eq 0) {
        Write-Host '[INFO] Restart checkpoint accepted and the previous server stopped.'
        exit 0
    }
    if (-not (Get-Process -Id $workerPid -ErrorAction SilentlyContinue)) {
        if (Test-RestartInProgress (Join-Path $root '.runtime')) {
            Write-Host '[INFO] Another worker owns this restart; using the existing restart.'
            exit 0
        }
        throw 'The independent restart worker exited before stopping the previous server.'
    }
    Start-Sleep -Milliseconds 250
} while ((Get-Date) -lt $deadline)

throw "Timed out waiting for the previous AgentPark server on port $port to stop."
