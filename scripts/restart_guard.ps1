function Open-RestartGuard([string]$RuntimeDir) {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    $path = Join-Path $RuntimeDir 'restart.lock'
    try {
        return [System.IO.File]::Open($path, [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch [System.IO.IOException] {
        if (($_.Exception.HResult -band 0xffff) -in @(32, 33)) { return $null }
        throw
    }
}

function Test-RestartInProgress([string]$RuntimeDir) {
    $probe = Open-RestartGuard $RuntimeDir
    if ($null -eq $probe) { return $true }
    $probe.Dispose()
    return $false
}
