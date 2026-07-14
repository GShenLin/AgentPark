param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$buildScript = Join-Path $root "build_and_run.bat"
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "build_and_run.bat not found: $buildScript"
}

$command = 'call "' + $buildScript.Replace('"', '""') + '"'
$process = Start-Process `
    -FilePath $env:ComSpec `
    -ArgumentList @("/d", "/c", $command) `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru

$process.Id
