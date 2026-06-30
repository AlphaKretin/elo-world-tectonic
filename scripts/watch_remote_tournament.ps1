# Aggregate live status across every remote shard, polled over SSH.
# Mirrors watch_tournament_parallel.ps1's display, but fetches each
# shard's status/attempting files in parallel (ForEach-Object -Parallel)
# since serial SSH round-trips across 10 hosts would make a 3s refresh
# interval meaningless. Run in its own terminal and leave it open -- read
# only, never touches the running watchdogs/Game processes.
#
# Globs across all formats per shard (elo_status_*_shard<N>.json), not
# just one -- since remote_run_tournament.sh works through a format
# sequence per-droplet independently, different shards can legitimately
# be on different formats (or have a finished singles file alongside an
# in-progress doubles file) at the same point in time.
param(
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt"),
    [int]$RefreshSeconds = 5
)

$hostList = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hostList) {
    Write-Output "No hosts found in $HostsFile"
    return
}

$lastAttempting = @{}
$lastAttemptingChangedAt = @{}

while ($true) {
    $snapshots = $hostList | ForEach-Object -ThrottleLimit $hostList.Count -Parallel {
        $thisHost = $_
        $remoteCmd = "for f in ~/elo-test/results/elo_status_*_shard*.json; do [ -f `"`$f`" ] && echo `"`$f:`" && cat `"`$f`"; done 2>/dev/null; echo '---ATTEMPTING---'; for f in ~/elo-test/results/elo_attempting_*_shard*.json; do [ -f `"`$f`" ] && cat `"`$f`"; done 2>/dev/null"
        $output = & ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$thisHost" $remoteCmd 2>$null
        [PSCustomObject]@{ HostName = $thisHost; Output = ($output -join "`n") }
    }

    # try/catch: Clear-Host throws "handle is invalid" when stdout isn't a
    # real interactive console (e.g. output redirected to a file/log) --
    # harmless to skip in that case, just less pretty.
    try { Clear-Host } catch {}
    Write-Output "ELO Tournament remote status (all formats, $($hostList.Count) droplets) -- Ctrl+C to stop watching (does not stop the tournament)"
    Write-Output "================================================================"

    $totalDone = 0
    $totalAll  = 0
    $anyError  = $false

    for ($i = 0; $i -lt $hostList.Count; $i++) {
        $thisHost = $hostList[$i]
        $snap = $snapshots | Where-Object { $_.HostName -eq $thisHost } | Select-Object -First 1
        $parts = if ($snap) { $snap.Output -split "---ATTEMPTING---" } else { @("", "") }
        $statusRaw = $parts[0].Trim()
        $attemptingRaw = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "" }

        Write-Output ""
        Write-Output "-- shard $i ($thisHost) --"
        if ($statusRaw) {
            Write-Output $statusRaw
            # Sum across every format's status line present, not just one.
            foreach ($m in [regex]::Matches($statusRaw, '"done":(\d+)'))  { $totalDone += [int]$m.Groups[1].Value }
            foreach ($m in [regex]::Matches($statusRaw, '"total":(\d+)')) { $totalAll  += [int]$m.Groups[1].Value }
            if ($statusRaw -match '"error":\{')    { $anyError = $true }
        } else {
            Write-Output "(no status yet / unreachable)"
        }

        if ($attemptingRaw -and $attemptingRaw -ne $lastAttempting[$i]) {
            $lastAttempting[$i] = $attemptingRaw
            $lastAttemptingChangedAt[$i] = Get-Date
        }
        if ($lastAttempting[$i]) {
            $sinceChange = [int]((Get-Date) - $lastAttemptingChangedAt[$i]).TotalSeconds
            Write-Output "attempting (unchanged ${sinceChange}s): $($lastAttempting[$i])"
        }
    }

    Write-Output ""
    Write-Output "================================================================"
    if ($totalAll -gt 0) {
        $pct = [math]::Round($totalDone * 100.0 / $totalAll, 3)
        Write-Output "AGGREGATE: $totalDone / $totalAll ($pct%)"
    }
    if ($anyError) {
        Write-Output "*** At least one shard reports a top-level error -- check its status above. ***"
    }
    Write-Output "Last refreshed: $(Get-Date -Format o)"

    Start-Sleep -Seconds $RefreshSeconds
}
