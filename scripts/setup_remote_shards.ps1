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
param(
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt"),
    [int]$ThrottleLimit = 10
)

$hosts = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hosts) {
    Write-Output "No hosts found in $HostsFile"
    return
}
Write-Output "Provisioning $($hosts.Count) droplet(s): $($hosts -join ', ')"

$ScriptDir = $PSScriptRoot

$hosts | ForEach-Object -ThrottleLimit $ThrottleLimit -Parallel {
    $thisHost = $_
    $scriptDir = $using:ScriptDir
    Write-Output "[$thisHost] copying provisioning scripts..."
    & scp -o StrictHostKeyChecking=accept-new `
        (Join-Path $scriptDir "remote_run_tournament.sh") `
        (Join-Path $scriptDir "remote_provision_shard.sh") `
        "root@${thisHost}:~/" 2>&1 | ForEach-Object { "[$thisHost] $_" }

    Write-Output "[$thisHost] running remote_provision_shard.sh (this takes a minute or two)..."
    & ssh -o StrictHostKeyChecking=accept-new "root@$thisHost" `
        "chmod +x ~/remote_provision_shard.sh ~/remote_run_tournament.sh && ~/remote_provision_shard.sh" 2>&1 |
        ForEach-Object { "[$thisHost] $_" }

    if ($LASTEXITCODE -eq 0) {
        Write-Output "[$thisHost] *** PROVISIONED OK ***"
    } else {
        Write-Output "[$thisHost] *** PROVISIONING FAILED (exit $LASTEXITCODE) -- check output above ***"
    }
}

Write-Output ""
Write-Output "Done. Re-run this script if any host reported a failure (idempotent)."
