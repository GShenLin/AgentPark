param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,

    [int]$StopTimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'

function Normalize-PathText {
    param([Parameter(Mandatory = $true)][string]$PathText)
    $cleanPath = $PathText.Trim().Trim('"')
    return [System.IO.Path]::GetFullPath($cleanPath).TrimEnd('\')
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    } catch [System.IO.FileNotFoundException] {
        return $null
    } catch [System.Management.Automation.ItemNotFoundException] {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "JSON file is empty: $Path"
    }
    return $raw | ConvertFrom-Json
}

function Get-ConfiguredServerPort {
    param([Parameter(Mandatory = $true)][string]$Root)
    $configPath = Join-Path $Root 'config\config.json'
    $config = Read-JsonFile -Path $configPath
    if ($null -eq $config -or $null -eq $config.server) {
        return 8766
    }
    if ($config.server.PSObject.Properties.Name -notcontains 'port') {
        return 8766
    }
    $port = [int]$config.server.port
    if ($port -le 0 -or $port -gt 65535) {
        throw "config/config.json field server.port must be between 1 and 65535."
    }
    return $port
}

function Test-ProjectProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)][string]$Root,
        [bool]$TrustWorkspaceIdentity = $false
    )
    $commandLine = [string]$ProcessInfo.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        return $false
    }
    $rootText = (Normalize-PathText -PathText $Root)
    $hasServerEntry = Test-ServerCommandLine -CommandLine $commandLine
    $hasCompanionCliEntry = Test-CompanionCliCommandLine -CommandLine $commandLine
    $hasWorkspaceRoot = $commandLine.IndexOf($rootText, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    if ($TrustWorkspaceIdentity) {
        return $hasServerEntry
    }
    if (-not $hasServerEntry -and -not $hasCompanionCliEntry) {
        return $false
    }
    return ($hasWorkspaceRoot -or (Test-ProcessTreeHasWorkspaceRoot -ProcessInfo $ProcessInfo -Root $Root))
}

function Test-ServerCommandLine {
    param([Parameter(Mandatory = $true)][string]$CommandLine)
    return (
        $CommandLine -like '*src.fast_api*' -or
        $CommandLine -like '*src\fast_api.py*' -or
        $CommandLine -like '*src/fast_api.py*'
    )
}

function Test-CompanionCliCommandLine {
    param([Parameter(Mandatory = $true)][string]$CommandLine)
    return (
        ($CommandLine -like '* -m src.cli chat*') -or
        ($CommandLine -like '*\src\cli.py chat*') -or
        ($CommandLine -like '*/src/cli.py chat*')
    )
}

function Get-ProjectProcessKind {
    param([Parameter(Mandatory = $true)][string]$CommandLine)
    if (Test-ServerCommandLine -CommandLine $CommandLine) {
        return 'server'
    }
    if (Test-CompanionCliCommandLine -CommandLine $CommandLine) {
        return 'companion-cli'
    }
    return 'unknown'
}

function Test-ProjectWrapperProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $processName = [string]$ProcessInfo.Name
    if ($processName -ine 'cmd.exe') {
        return $false
    }
    $commandLine = [string]$ProcessInfo.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        return $false
    }
    $rootText = (Normalize-PathText -PathText $Root)
    return (
        $commandLine.IndexOf($rootText, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and (
            $commandLine -like '*build_and_run.bat*' -or
            $commandLine -like '*Restart.bat*'
        )
    )
}

function Get-CimProcessById {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
}

function Test-ProcessTreeHasWorkspaceRoot {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)][string]$Root,
        [int]$MaxDepth = 4
    )
    $rootText = (Normalize-PathText -PathText $Root)
    $current = $ProcessInfo
    for ($depth = 0; $depth -lt $MaxDepth; $depth++) {
        $parentId = [int]$current.ParentProcessId
        if ($parentId -le 0) {
            return $false
        }
        $parent = Get-CimProcessById -ProcessId $parentId
        if ($null -eq $parent) {
            return $false
        }
        $parentCommandLine = [string]$parent.CommandLine
        if (-not [string]::IsNullOrWhiteSpace($parentCommandLine) -and $parentCommandLine.IndexOf($rootText, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
        $current = $parent
    }
    return $false
}

function Add-ProcessCandidate {
    param(
        [Parameter(Mandatory = $true)]$Map,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Reason,
        [Parameter(Mandatory = $true)][string]$Root,
        [bool]$TrustWorkspaceIdentity = $false
    )
    if ($ProcessId -le 0 -or $Map.ContainsKey($ProcessId)) {
        return
    }
    $procInfo = Get-CimProcessById -ProcessId $ProcessId
    if ($null -eq $procInfo) {
        return
    }
    if (-not (Test-ProjectProcess -ProcessInfo $procInfo -Root $Root -TrustWorkspaceIdentity $TrustWorkspaceIdentity)) {
        Write-Host "[WARN] Ignoring PID $ProcessId from $Reason because it is not an AgentPark server for this workspace."
        Write-Host "       $($procInfo.CommandLine)"
        return
    }
    $Map[$ProcessId] = [pscustomobject]@{
        Pid = $ProcessId
        Reason = $Reason
        Kind = Get-ProjectProcessKind -CommandLine ([string]$procInfo.CommandLine)
        Name = $procInfo.Name
        CommandLine = $procInfo.CommandLine
    }
}

function Get-ProjectWrapperProcessIds {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)][string]$Root,
        [int]$MaxDepth = 4
    )
    $rootText = (Normalize-PathText -PathText $Root)
    $ids = @()
    $current = $ProcessInfo
    for ($depth = 0; $depth -lt $MaxDepth; $depth++) {
        $parentId = [int]$current.ParentProcessId
        if ($parentId -le 0) {
            return $ids
        }
        $parent = Get-CimProcessById -ProcessId $parentId
        if ($null -eq $parent) {
            return $ids
        }
        $parentName = [string]$parent.Name
        $parentCommandLine = [string]$parent.CommandLine
        $isCmd = $parentName -ieq 'cmd.exe'
        $isProjectScript = $parentCommandLine.IndexOf($rootText, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and (
            $parentCommandLine -like '*build_and_run.bat*' -or
            $parentCommandLine -like '*Restart.bat*'
        )
        if ($isCmd -and $isProjectScript) {
            $ids += $parentId
        }
        $current = $parent
    }
    return $ids
}

function Get-CurrentWrapperProcessId {
    $currentProcess = Get-CimProcessById -ProcessId ([System.Diagnostics.Process]::GetCurrentProcess().Id)
    if ($null -eq $currentProcess) {
        return 0
    }
    $parent = Get-CimProcessById -ProcessId ([int]$currentProcess.ParentProcessId)
    if ($null -eq $parent -or [string]$parent.Name -ine 'cmd.exe') {
        return 0
    }
    return [int]$parent.ProcessId
}

function Get-ListeningPids {
    param([Parameter(Mandatory = $true)][int]$Port)
    return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-LocalClientHost {
    param([Parameter(Mandatory = $true)][string]$HostText)
    $cleanHost = $HostText.Trim()
    if ($cleanHost -eq '0.0.0.0' -or $cleanHost -eq '::' -or $cleanHost -eq '[::]') {
        return '127.0.0.1'
    }
    if ([string]::IsNullOrWhiteSpace($cleanHost)) {
        return '127.0.0.1'
    }
    return $cleanHost
}

function Request-WebUiClose {
    param(
        [Parameter(Mandatory = $true)][string]$HostText,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $clientHost = Get-LocalClientHost -HostText $HostText
    $uri = "http://${clientHost}:${Port}/api/system/webui-close"
    try {
        Invoke-RestMethod -Method Post -Uri $uri -Body '{"reason":"restart"}' -ContentType 'application/json' -TimeoutSec 2 | Out-Null
        Write-Host "[INFO] Requested WebUI page close: $uri"
        Start-Sleep -Milliseconds 1500
    } catch {
        Write-Host "[WARN] Failed to request WebUI page close before stopping server: $($_.Exception.Message)"
    }
}

function Wait-ProcessesExited {
    param(
        [Parameter(Mandatory = $true)][int[]]$Pids,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $remaining = @($Pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        if ($remaining.Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    return $false
}

$root = Normalize-PathText -PathText $WorkspaceRoot
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Workspace root does not exist: $root"
}

$configuredPort = Get-ConfiguredServerPort -Root $root
$runtimeDir = Join-Path $root '.runtime'
$pidFile = Join-Path $runtimeDir 'aitools-server.pid'
$candidates = @{}
$wrapperProcessIds = @{}
$currentWrapperProcessId = Get-CurrentWrapperProcessId

Write-Host "[INFO] Workspace: $root"
Write-Host "[INFO] Configured server port: $configuredPort"

$pidPayload = Read-JsonFile -Path $pidFile
if ($null -ne $pidPayload) {
    $payloadRoot = Normalize-PathText -PathText ([string]$pidPayload.workspace_root)
    if ($pidPayload.app -ne 'AgentPark' -or $pidPayload.kind -ne 'fast_api_server' -or $payloadRoot -ine $root) {
        throw "Refusing to trust pid file with unexpected identity: $pidFile"
    }
    Add-ProcessCandidate -Map $candidates -ProcessId ([int]$pidPayload.pid) -Reason 'pid-file' -Root $root -TrustWorkspaceIdentity $true
}

foreach ($listeningProcessId in (Get-ListeningPids -Port $configuredPort)) {
    Add-ProcessCandidate -Map $candidates -ProcessId ([int]$listeningProcessId) -Reason "configured-port:$configuredPort" -Root $root
}

$projectProcesses = @(Get-CimInstance Win32_Process | Where-Object { Test-ProjectProcess -ProcessInfo $_ -Root $root })
foreach ($proc in $projectProcesses) {
    Add-ProcessCandidate -Map $candidates -ProcessId ([int]$proc.ProcessId) -Reason 'command-line-scan' -Root $root
}

$projectWrapperProcesses = @(Get-CimInstance Win32_Process | Where-Object { Test-ProjectWrapperProcess -ProcessInfo $_ -Root $root })
foreach ($proc in $projectWrapperProcesses) {
    $wrapperProcessId = [int]$proc.ProcessId
    if ($wrapperProcessId -eq [int]$currentWrapperProcessId) {
        continue
    }
    if (-not $wrapperProcessIds.ContainsKey($wrapperProcessId)) {
        $wrapperProcessIds[$wrapperProcessId] = $true
    }
}

if ($candidates.Count -eq 0 -and $wrapperProcessIds.Count -eq 0) {
    Write-Host '[INFO] No running AgentPark process found for this workspace.'
} else {
    $processIds = @($candidates.Keys | Sort-Object)
    $hasServerCandidate = @($candidates.Values | Where-Object { $_.Kind -eq 'server' }).Count -gt 0
    if ($hasServerCandidate) {
        $webUiHost = '127.0.0.1'
        $webUiPort = $configuredPort
        if ($null -ne $pidPayload) {
            if ($pidPayload.PSObject.Properties.Name -contains 'host') {
                $webUiHost = [string]$pidPayload.host
            }
            if ($pidPayload.PSObject.Properties.Name -contains 'port') {
                $webUiPort = [int]$pidPayload.port
            }
        }
        Request-WebUiClose -HostText $webUiHost -Port $webUiPort
    }
    foreach ($processId in $processIds) {
        $procInfo = Get-CimProcessById -ProcessId ([int]$processId)
        if ($null -eq $procInfo) {
            continue
        }
        foreach ($wrapperProcessId in (Get-ProjectWrapperProcessIds -ProcessInfo $procInfo -Root $root)) {
            if (-not $wrapperProcessIds.ContainsKey($wrapperProcessId)) {
                $wrapperProcessIds[$wrapperProcessId] = $true
            }
        }
    }
    foreach ($processId in $processIds) {
        $candidate = $candidates[$processId]
        Write-Host "[INFO] Stopping PID $processId ($($candidate.Reason)): $($candidate.Name)"
    }
    if ($processIds.Count -gt 0) {
        foreach ($processId in $processIds) {
            Stop-Process -Id $processId -ErrorAction SilentlyContinue
        }
        if (-not (Wait-ProcessesExited -Pids $processIds -TimeoutSeconds $StopTimeoutSeconds)) {
            $remainingProcessIds = @($processIds | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
            foreach ($processId in $remainingProcessIds) {
                Write-Host "[WARN] PID $processId did not exit within $StopTimeoutSeconds seconds; forcing termination."
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
            if (-not (Wait-ProcessesExited -Pids $remainingProcessIds -TimeoutSeconds 5)) {
                throw 'Failed to stop one or more AgentPark processes.'
            }
        }
    }
    foreach ($wrapperProcessId in @($wrapperProcessIds.Keys | Sort-Object)) {
        if ([int]$wrapperProcessId -eq [int]$currentWrapperProcessId) {
            continue
        }
        if (Get-Process -Id $wrapperProcessId -ErrorAction SilentlyContinue) {
            Write-Host "[INFO] Closing wrapper cmd PID $wrapperProcessId."
            Stop-Process -Id $wrapperProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

foreach ($listeningProcessId in (Get-ListeningPids -Port $configuredPort)) {
    $procInfo = Get-CimProcessById -ProcessId ([int]$listeningProcessId)
    if ($null -ne $procInfo) {
        throw "Configured port $configuredPort is still occupied by PID ${listeningProcessId}: $($procInfo.CommandLine)"
    }
}

if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
    $stalePayload = Read-JsonFile -Path $pidFile
    $stalePid = if ($null -ne $stalePayload) { [int]$stalePayload.pid } else { 0 }
    if ($stalePid -le 0 -or -not (Get-Process -Id $stalePid -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $pidFile -Force
        Write-Host "[INFO] Removed stale pid file: $pidFile"
    }
}

Write-Host '[INFO] Stop phase complete.'
