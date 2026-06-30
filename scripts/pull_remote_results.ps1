# Pulls each droplet's results/ files back into results/remote/ (a
# subdirectory, NOT the top-level results/ used by local shard runs --
# both use the identical elo_results_<format>_shard<N>.jsonl naming
# convention, so pulling directly into results/ silently overwrites
# same-numbered local shard data with remote data or vice versa. Hit
# this for real during testing: a remote shard0 pull clobbered local
# shard0 test data. Point analysis scripts at results/remote/ explicitly
# for this run's data instead of relying on the default results/ glob.
# Safe to run repeatedly while a tournament is still in progress (e.g. to
# check interim results) -- scp overwrites, doesn't merge or duplicate.
param(
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt")
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results\remote"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

$hostList = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hostList) {
    Write-Output "No hosts found in $HostsFile"
    return
}

$hostList | ForEach-Object -ThrottleLimit $hostList.Count -Parallel {
    $thisHost = $_
    $resultsDir = $using:ResultsDir
    Write-Output "[$thisHost] pulling results..."
    & scp -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -q `
        "root@${thisHost}:~/elo-test/results/*" "$resultsDir/" 2>&1 |
        ForEach-Object { "[$thisHost] $_" }
}

Write-Output ""
Write-Output "Done. Results synced to $ResultsDir"
