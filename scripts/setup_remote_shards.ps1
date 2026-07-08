# Provisions every droplet listed in remote_hosts.txt in parallel: copies
# the two remote_*.sh scripts over via scp, then runs remote_provision_shard.sh
# via ssh (installs deps, clones the fork, debug+compiles, validates with a
# single test battle). Safe to re-run -- remote_provision_shard.sh is
# idempotent (skips the clone if already done, always re-runs the cheap
# compile+validate steps).
#
# Run this once before run_remote_parallel.ps1. Each droplet takes roughly
# 1-2 minutes (apt install + clone + compile + validate battle); run in
# parallel via ForEach-Object -Parallel rather than sequentially, since
# with 10 droplets that's the difference between ~90s and ~15 minutes.
#
# remote_provision_shard.sh does a `git reset --hard`+`git clean -fdx` on
# already-provisioned droplets to pick up newly pushed commits, which wipes
# any results/logs still sitting on that droplet. Pulling isn't otherwise on
# a schedule -- it happens "at some point after a run", not right after each
# droplet finishes -- so without a pull-first step here, re-provisioning
# could silently destroy not-yet-pulled data. So by default this script
# pulls+archives each droplet's results/ (same mechanism as
# pull_remote_results.ps1 + archive_run.ps1: move, don't delete) before ever
# touching that droplet. Use -SkipResultsPull to opt out (e.g. you already
# just pulled and know there's nothing pending).
# -SubsetPairsPath, if given, scp's a local exact-pair-rerun manifest (see
# tournament.rb's SUBSET_PAIRS_PATH) up to every droplet at
# ~/elo-test/Analysis/subset_pairs.tsv -- unlike setup_shards.ps1's local
# shards (which pick up anything dropped into vendor/tectonic-content/Analysis/
# for free via its robocopy /MIR of the whole game dir), remote_provision_shard.sh
# provisions via a fresh git clone, so a manifest living only in this repo's
# working tree never reaches a droplet on its own. Point -SubsetPairsPath at
# run_remote_parallel.ps1's own -SubsetPairsPath at
# ~/elo-test/Analysis/subset_pairs.tsv to match.
param(
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt"),
    [int]$ThrottleLimit = 10,
    [switch]$SkipResultsPull,
    [string]$SubsetPairsPath = ""
)

$hosts = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hosts) {
    Write-Output "No hosts found in $HostsFile"
    return
}
Write-Output "Provisioning $($hosts.Count) droplet(s): $($hosts -join ', ')"

. (Join-Path $PSScriptRoot "archive_lib.ps1")

$ScriptDir = $PSScriptRoot
$RepoRoot  = Split-Path -Parent $PSScriptRoot
$PullDir   = Join-Path $RepoRoot "results\remote"

if (-not $SkipResultsPull) {
    New-Item -ItemType Directory -Force -Path $PullDir | Out-Null
    Write-Output "Pulling any not-yet-collected results off each droplet before provisioning wipes them..."
    $hosts | ForEach-Object -ThrottleLimit $ThrottleLimit -Parallel {
        $thisHost = $_
        $pullDir = $using:PullDir
        & scp -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -q `
            "root@${thisHost}:~/elo-test/results/*" "$pullDir/" 2>$null
    }

    $pulled = @(Get-ChildItem -Path $PullDir -File -ErrorAction SilentlyContinue)
    if ($pulled.Count -gt 0) {
        $archiveDir = New-ArchiveDir -Label "pre_provision"
        Write-Output "Pulled $($pulled.Count) file(s) -- archiving to $archiveDir (moved, not deleted)"
        $pulled | Move-Item -Destination $archiveDir
    } else {
        Write-Output "Nothing pending on any droplet."
    }
}

$hosts | ForEach-Object -ThrottleLimit $ThrottleLimit -Parallel {
    $thisHost = $_
    $scriptDir = $using:ScriptDir
    Write-Output "[$thisHost] copying provisioning scripts..."
    & scp -o StrictHostKeyChecking=accept-new `
        (Join-Path $scriptDir "remote_run_tournament.sh") `
        (Join-Path $scriptDir "remote_provision_shard.sh") `
        "root@${thisHost}:~/" 2>&1 | ForEach-Object { "[$thisHost] $_" }

    Write-Output "[$thisHost] running remote_provision_shard.sh (this takes a minute or two)..."
    # -n (redirect stdin from /dev/null): without it, ssh.exe on Windows can
    # hang indefinitely waiting for stdin EOF that never arrives inside a
    # ForEach-Object -Parallel runspace, even though the remote command has
    # long since finished -- the remote side shows zero child processes left
    # under its sshd session while the *local* ssh.exe sits there for
    # 20+ minutes. Cost real time misdiagnosing "provisioning failures" that
    # were actually just this hang (then -Force-killing the hung local
    # process, which makes $LASTEXITCODE report -1 and falsely look like a
    # real remote failure on top of it). See [[feedback-cross-tool-environment-gotchas]].
    & ssh -n -o StrictHostKeyChecking=accept-new "root@$thisHost" `
        "chmod +x ~/remote_provision_shard.sh ~/remote_run_tournament.sh && ~/remote_provision_shard.sh" 2>&1 |
        ForEach-Object { "[$thisHost] $_" }

    if ($LASTEXITCODE -eq 0) {
        Write-Output "[$thisHost] *** PROVISIONED OK ***"
    } else {
        Write-Output "[$thisHost] *** PROVISIONING FAILED (exit $LASTEXITCODE) -- check output above ***"
    }
}

if ($SubsetPairsPath) {
    if (-not (Test-Path $SubsetPairsPath)) {
        throw "-SubsetPairsPath '$SubsetPairsPath' not found"
    }
    Write-Output ""
    Write-Output "Pushing subset pairs manifest to every droplet (~/elo-test/Analysis/subset_pairs.tsv)..."
    $hosts | ForEach-Object -ThrottleLimit $ThrottleLimit -Parallel {
        $thisHost = $_
        $manifestPath = $using:SubsetPairsPath
        & ssh -n -o StrictHostKeyChecking=accept-new "root@$thisHost" "mkdir -p ~/elo-test/Analysis" 2>&1 | ForEach-Object { "[$thisHost] $_" }
        & scp -o StrictHostKeyChecking=accept-new -q "$manifestPath" "root@${thisHost}:~/elo-test/Analysis/subset_pairs.tsv" 2>&1 |
            ForEach-Object { "[$thisHost] $_" }
        Write-Output "[$thisHost] manifest pushed."
    }
}

Write-Output ""
Write-Output "Done. Re-run this script if any host reported a failure (idempotent)."
