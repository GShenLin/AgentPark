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

function Test-GitPathExists {
    param([Parameter(Mandatory = $true)][string]$GitPath)

    $path = Get-GitOutputText -Arguments @('rev-parse', '--git-path', $GitPath)
    return (Test-Path -LiteralPath $path)
}

function Test-RebaseInProgress {
    return ((Test-GitPathExists -GitPath 'rebase-merge') -or (Test-GitPathExists -GitPath 'rebase-apply'))
}

function Assert-NoInterruptedGitOperation {
    if (Test-RebaseInProgress) {
        throw 'A git rebase is already in progress. Resolve or abort it before restarting.'
    }
    if (Test-GitPathExists -GitPath 'MERGE_HEAD') {
        throw 'A git merge is already in progress. Resolve or abort it before restarting.'
    }
    if (Test-GitPathExists -GitPath 'CHERRY_PICK_HEAD') {
        throw 'A git cherry-pick is already in progress. Resolve or abort it before restarting.'
    }
}

function Get-WorkingTreeStatus {
    return @(Get-GitOutputLines -Arguments @('status', '--porcelain=v1'))
}

function Test-WorkingTreeDirty {
    return ((Get-WorkingTreeStatus).Count -gt 0)
}

function Save-LocalChangesAsCommit {
    if (-not (Test-WorkingTreeDirty)) {
        Write-Host '[INFO] Working tree is clean. No local commit is needed.'
        return
    }

    Write-Host '[INFO] Local changes detected. Creating an automatic commit before rebase.'
    Invoke-Git -Arguments @('add', '-A', '--', '.') | Out-Null

    $statusAfterAdd = @(Get-GitOutputLines -Arguments @('status', '--porcelain=v1'))
    if ($statusAfterAdd.Count -eq 0) {
        Write-Host '[INFO] No committable changes remain after staging.'
        return
    }

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'
    Invoke-Git -Arguments @('commit', '-m', "chore: auto-save local changes before restart ($timestamp)") | Out-Null
}

function Get-CurrentBranchName {
    $branch = Get-GitOutputText -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')
    if ($branch -eq 'HEAD') {
        throw 'Repository is in detached HEAD state. Cannot rebase and push automatically.'
    }
    return $branch
}

function Get-UpstreamRef {
    $upstream = Get-GitOutputText -Arguments @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
    if ([string]::IsNullOrWhiteSpace($upstream)) {
        throw 'Current branch has no upstream. Configure it before using Restart.bat.'
    }
    return $upstream
}

function Get-UnmergedPaths {
    return @(Get-GitOutputLines -Arguments @('diff', '--name-only', '--diff-filter=U'))
}

function Test-GitStageExists {
    param(
        [Parameter(Mandatory = $true)][int]$Stage,
        [Parameter(Mandatory = $true)][string]$Path
    )

    & git cat-file -e (":$Stage`:$Path") 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-IndexOrWorkTreeHasChanges {
    & git diff --cached --quiet
    $cachedExitCode = $LASTEXITCODE
    & git diff --quiet
    $workTreeExitCode = $LASTEXITCODE

    if ($cachedExitCode -gt 1) {
        throw "git diff --cached --quiet failed with exit code $cachedExitCode."
    }
    if ($workTreeExitCode -gt 1) {
        throw "git diff --quiet failed with exit code $workTreeExitCode."
    }

    return ($cachedExitCode -eq 1 -or $workTreeExitCode -eq 1)
}

function Resolve-ConflictsWithUpstreamVersion {
    $paths = @(Get-UnmergedPaths)
    if ($paths.Count -eq 0) {
        return
    }

    Write-Host '[INFO] Resolving rebase conflicts with the upstream/server version.'
    foreach ($path in $paths) {
        if (Test-GitStageExists -Stage 2 -Path $path) {
            Invoke-Git -Arguments @('checkout', '--ours', '--', $path) | Out-Null
            Invoke-Git -Arguments @('add', '--', $path) | Out-Null
        } else {
            Invoke-Git -Arguments @('rm', '-f', '--ignore-unmatch', '--', $path) | Out-Null
        }
    }

    $remaining = @(Get-UnmergedPaths)
    if ($remaining.Count -gt 0) {
        throw "Unable to resolve all conflicts automatically: $($remaining -join ', ')"
    }
}

function Complete-RebaseUsingUpstreamVersion {
    param([Parameter(Mandatory = $true)][string]$Upstream)

    Write-Host "[INFO] Rebasing current branch onto $Upstream. Conflicting hunks prefer upstream/server files."
    $exitCode = Invoke-Git -Arguments @('rebase', '-X', 'ours', $Upstream) -AllowFailure
    if ($exitCode -eq 0) {
        return
    }
    if (-not (Test-RebaseInProgress)) {
        throw "git rebase failed before entering a resumable rebase state."
    }

    while (Test-RebaseInProgress) {
        Resolve-ConflictsWithUpstreamVersion

        if (-not (Test-IndexOrWorkTreeHasChanges)) {
            Write-Host '[INFO] Current replayed commit is empty after taking upstream/server conflicts. Skipping it.'
            Invoke-Git -Arguments @('rebase', '--skip') | Out-Null
            continue
        }

        $continueExitCode = Invoke-Git -Arguments @('-c', 'core.editor=cmd /c exit 0', 'rebase', '--continue') -AllowFailure
        if ($continueExitCode -ne 0) {
            if ((Get-UnmergedPaths).Count -eq 0 -and -not (Test-IndexOrWorkTreeHasChanges)) {
                Write-Host '[INFO] Rebase step produced no changes. Skipping it.'
                Invoke-Git -Arguments @('rebase', '--skip') | Out-Null
                continue
            }
            throw "git rebase --continue failed with exit code $continueExitCode."
        }
    }
}

function Assert-CleanWorkingTree {
    $status = @(Get-WorkingTreeStatus)
    if ($status.Count -gt 0) {
        throw "Working tree is not clean after sync:`n$($status -join "`n")"
    }
}

Set-Location -LiteralPath $WorkspaceRoot

try {
    Get-GitOutputText -Arguments @('rev-parse', '--is-inside-work-tree') | Out-Null
    Assert-NoInterruptedGitOperation
    $branch = Get-CurrentBranchName
    $upstream = Get-UpstreamRef
    Write-Host "[INFO] Syncing branch $branch with upstream $upstream."

    Save-LocalChangesAsCommit
    Invoke-Git -Arguments @('fetch', '--prune') | Out-Null
    Complete-RebaseUsingUpstreamVersion -Upstream $upstream
    Assert-CleanWorkingTree
    Invoke-Git -Arguments @('push') | Out-Null
    Assert-CleanWorkingTree

    Write-Host '[INFO] Repository sync completed. Working tree is clean.'
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
