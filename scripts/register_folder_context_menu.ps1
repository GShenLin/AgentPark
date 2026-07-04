param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot
)

$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$bat = Join-Path $root "build_and_run.bat"
if (-not (Test-Path -LiteralPath $bat -PathType Leaf)) {
    throw "build_and_run.bat not found: $bat"
}
$askHereBat = Join-Path $root "scripts\agentpark_ask_here.bat"
if (-not (Test-Path -LiteralPath $askHereBat -PathType Leaf)) {
    throw "agentpark_ask_here.bat not found: $askHereBat"
}
$askHereHidden = Join-Path $root "scripts\agentpark_ask_here_hidden.vbs"
if (-not (Test-Path -LiteralPath $askHereHidden -PathType Leaf)) {
    throw "agentpark_ask_here_hidden.vbs not found: $askHereHidden"
}

$entries = @(
    @{
        Path = "HKCU:\Software\Classes\*\shell\AgentPark"
        Command = 'wscript.exe "' + $askHereHidden + '" "%1"'
    },
    @{
        Path = "HKCU:\Software\Classes\Directory\shell\AgentPark"
        Command = 'wscript.exe "' + $askHereHidden + '" "%1"'
    },
    @{
        Path = "HKCU:\Software\Classes\Directory\Background\shell\AgentPark"
        Command = 'wscript.exe "' + $askHereHidden + '" "%V"'
    }
)

$intendedAgentParkShellPaths = @(
    "HKEY_CURRENT_USER\Software\Classes\*\shell\AgentPark",
    "HKEY_CURRENT_USER\Software\Classes\Directory\shell\AgentPark",
    "HKEY_CURRENT_USER\Software\Classes\Directory\Background\shell\AgentPark"
)

function Ensure-RegistryKey {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (Test-Path -LiteralPath $Path) {
        return
    }
    if (-not $Path.StartsWith("HKCU:\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Only HKCU registry paths are supported: $Path"
    }
    $relativePath = $Path.Substring("HKCU:\".Length)
    $currentKey = [Microsoft.Win32.Registry]::CurrentUser
    $currentKeyShouldClose = $false
    foreach ($part in ($relativePath -split "\\")) {
        if ([string]::IsNullOrWhiteSpace($part)) {
            continue
        }
        $nextKey = $currentKey.CreateSubKey($part)
        if ($null -eq $nextKey) {
            throw "Failed to create registry key: $Path"
        }
        if ($currentKeyShouldClose) {
            $currentKey.Close()
        }
        $currentKey = $nextKey
        $currentKeyShouldClose = $true
    }
    if ($currentKeyShouldClose) {
        $currentKey.Close()
    }
}

function Set-RegistryStringValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    Ensure-RegistryKey -Path $Path
    $relativePath = $Path.Substring("HKCU:\".Length)
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($relativePath, $true)
    if ($null -eq $key) {
        throw "Failed to open registry key for writing: $Path"
    }
    try {
        $key.SetValue($Name, $Value, [Microsoft.Win32.RegistryValueKind]::String)
    } finally {
        $key.Close()
    }
}

function Remove-StaleAgentParkShellKeys {
    $intended = @{}
    foreach ($path in $intendedAgentParkShellPaths) {
        $intended[$path.ToLowerInvariant()] = $true
    }
    $classesRoot = "HKCU:\Software\Classes"
    if (-not (Test-Path -LiteralPath $classesRoot)) {
        return
    }
    $staleKeys = @(
        Get-ChildItem -LiteralPath $classesRoot -Recurse -ErrorAction SilentlyContinue |
            Where-Object {
                $_.PSChildName -eq "AgentPark" -and
                $_.Name.EndsWith("\shell\AgentPark", [System.StringComparison]::OrdinalIgnoreCase) -and
                -not $intended.ContainsKey($_.Name.ToLowerInvariant())
            } |
            Select-Object -ExpandProperty PSPath
    )
    foreach ($path in $staleKeys) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Remove-StaleAgentParkShellKeys

foreach ($entry in $entries) {
    Set-RegistryStringValue -Path $entry.Path -Name "MUIVerb" -Value "AgentPark"
    Set-RegistryStringValue -Path $entry.Path -Name "Icon" -Value $bat

    $commandPath = Join-Path $entry.Path "command"
    Set-RegistryStringValue -Path $commandPath -Name "" -Value $entry.Command
}
