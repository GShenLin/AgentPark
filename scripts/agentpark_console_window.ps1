param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,

    [Parameter(Mandatory = $true)]
    [ValidateSet("Toggle", "Hide", "Show")]
    [string]$Action
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class AgentParkConsoleWindow
{
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
"@

$root = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$statePath = Join-Path (Join-Path $root ".runtime") "agentpark-cli-window.json"

function Get-RegisteredWindow {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "Companion CLI is not running. Start build_and_run.bat first."
    }
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedRoot = [System.IO.Path]::GetFullPath([string]$state.workspace_root)
    if (-not $expectedRoot.Equals($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Companion CLI registration belongs to another workspace."
    }
    $cliPid = [int]$state.pid
    if ($cliPid -le 0 -or $null -eq (Get-Process -Id $cliPid -ErrorAction SilentlyContinue)) {
        throw "The registered Companion CLI process is no longer running."
    }
    $handleValue = [Int64]$state.handle
    if ($handleValue -le 0) {
        throw "AgentPark console registration contains an invalid window handle."
    }
    $handle = [IntPtr]::new($handleValue)
    if (-not [AgentParkConsoleWindow]::IsWindow($handle)) {
        throw "The registered AgentPark console window no longer exists. Start build_and_run.bat again."
    }
    return $handle
}

$handle = Get-RegisteredWindow
$visible = [AgentParkConsoleWindow]::IsWindowVisible($handle)
$show = $Action -eq "Show" -or ($Action -eq "Toggle" -and -not $visible)
$command = if ($show) { 9 } else { 0 }
[void][AgentParkConsoleWindow]::ShowWindowAsync($handle, $command)
