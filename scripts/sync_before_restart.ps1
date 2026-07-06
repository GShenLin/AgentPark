param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$AllowFailure
    )

    Write-Host "[GIT] git $($Arguments -join ' ')"
    & git @Arguments | ForEach-Object { Write-Host ([string]$_) }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "git $($Arguments -join ' ') failed with exit code $exitCode."
    }
    return $exitCode
}

function Get-GitOutputLines {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = @(& git @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $exitCode.`n$($output -join "`n")"
    }
    return @($output | ForEach-Object { [string]$_ })
}

function Get-GitOutputText {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    return ((Get-GitOutputLines -Arguments $Arguments) -join "`n").Trim()
}

function Get-WorkingTreeStatus {
    return @(Get-GitOutputLines -Arguments @('status', '--porcelain=v1'))
}

function Test-WorkingTreeClean {
    return ((Get-WorkingTreeStatus).Count -eq 0)
}

function Get-UpstreamRef {
    $upstream = Get-GitOutputText -Arguments @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
    if ([string]::IsNullOrWhiteSpace($upstream)) {
        throw 'Current branch has no upstream. Cannot pull updates before startup.'
    }
    return $upstream
}

Set-Location -LiteralPath $WorkspaceRoot

try {
    Get-GitOutputText -Arguments @('rev-parse', '--is-inside-work-tree') | Out-Null

    if (-not (Test-WorkingTreeClean)) {
        Write-Host '[INFO] Working tree has local changes. Skipping repository update.'
        exit 0
    }

    $upstream = Get-UpstreamRef
    Write-Host "[INFO] Working tree is clean. Pulling updates from $upstream with rebase."
    Invoke-Git -Arguments @('pull', '--rebase') | Out-Null
    Write-Host '[INFO] Repository update completed.'
} catch {
    Write-Host "[WARN] $($_.Exception.Message)" -ForegroundColor Yellow
    exit 1
}
