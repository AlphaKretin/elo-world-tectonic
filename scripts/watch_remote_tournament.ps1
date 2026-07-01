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

# tournament.rb's writeStatus/writeAttempting (ELO Tournament/tournament.rb)
# write flat, single-line JSON with no trailing newline, and the remote glob
# loop below concatenates every matching file back-to-back with no
# separator between them. So "path1:{json1}path2:{json2}" is what actually
# comes back over SSH when a shard has status/attempting files for more
# than one format. Split on a file path immediately followed by ":" (paths
# never contain "{"/"}"/whitespace) to recover each (path, json) pair, and
# split concatenated attempting blobs on the "}{" boundary between objects.
function Split-StatusBlobs([string]$raw) {
    $pairs = @()
    $parts = [regex]::Split($raw, '([^\s{}]+\.json):')
    for ($j = 1; $j -lt $parts.Count; $j += 2) {
        $path = $parts[$j]
        $jsonText = if ($j + 1 -lt $parts.Count) { $parts[$j + 1].Trim() } else { "" }
        if (-not $jsonText) { continue }
        $pairs += [PSCustomObject]@{ Path = $path; Json = $jsonText }
    }
    return $pairs
}

function Split-AttemptingBlobs([string]$raw) {
    return [regex]::Split($raw, '(?<=\})\s*(?=\{)') | Where-Object { $_.Trim() }
}

function Get-ShardFormatLabel([string]$path) {
    if ($path -match 'elo_(?:status|attempting)_(.+)_shard\d+\.json$') { return $Matches[1] }
    return $path
}

# Renders a duration (in seconds, possibly fractional) as [Dd] HH:MM:SS.
function Format-Duration($seconds) {
    if ($null -eq $seconds) { return "n/a" }
    $ts = [TimeSpan]::FromSeconds([double]$seconds)
    if ($ts.Days -ne 0) { return "{0}d {1:D2}:{2:D2}:{3:D2}" -f $ts.Days, [Math]::Abs($ts.Hours), [Math]::Abs($ts.Minutes), [Math]::Abs($ts.Seconds) }
    return "{0:D2}:{1:D2}:{2:D2}" -f $ts.Hours, $ts.Minutes, $ts.Seconds
}

function Write-StatusEntry([PSCustomObject]$d, [string]$formatLabel) {
    $state = if ($d.error) { "ERROR" } elseif ($d.finished) { "FINISHED" } else { "running" }
    Write-Output "  [$formatLabel] $state -- $($d.done)/$($d.total) ($($d.percent)%)"
    $rateText = if ($null -ne $d.rate_per_s) { "$($d.rate_per_s) battles/s" } else { "n/a" }
    Write-Output "    elapsed: $(Format-Duration $d.elapsed_s)  rate: $rateText"
    if (-not $d.finished -and $null -ne $d.eta_s) {
        $etaClock = (Get-Date).AddSeconds([double]$d.eta_s)
        Write-Output "    ETA: $(Format-Duration $d.eta_s) remaining -- around $($etaClock.ToString('yyyy-MM-dd HH:mm:ss'))"
    }
    if ($d.error) {
        Write-Output "    *** ERROR: $($d.error.error_class): $($d.error.error_message) ***"
    }
    Write-Output "    updated_at: $($d.updated_at)"
}

function Write-AttemptingEntry([PSCustomObject]$a) {
    Write-Output "  [$($a.format)] $($a.trainer1) vs $($a.trainer2) (seed $($a.seed))"
}

$hostList = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hostList) {
    Write-Output "No hosts found in $HostsFile"
    return
}

$lastAttempting = @{}
$lastAttemptingChangedAt = @{}
$lastAttemptingEntries = @{}

while ($true) {
    $snapshots = $hostList | ForEach-Object -ThrottleLimit $hostList.Count -Parallel {
        $thisHost = $_
        $remoteCmd = "for f in ~/elo-test/results/elo_status_*_shard*.json; do [ -f `"`$f`" ] && echo `"`$f:`" && cat `"`$f`"; done 2>/dev/null; echo '---ATTEMPTING---'; for f in ~/elo-test/results/elo_attempting_*_shard*.json; do [ -f `"`$f`" ] && cat `"`$f`"; done 2>/dev/null"
        # -n: see setup_remote_shards.ps1's comment on the same flag.
        $output = & ssh -n -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$thisHost" $remoteCmd 2>$null
        [PSCustomObject]@{ HostName = $thisHost; Output = ($output -join "`n"); SshFailed = ($LASTEXITCODE -ne 0) }
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
        $statusBlobs = if ($statusRaw) { Split-StatusBlobs $statusRaw } else { @() }
        if ($statusBlobs) {
            foreach ($blob in $statusBlobs) {
                $formatLabel = Get-ShardFormatLabel $blob.Path
                try {
                    $d = $blob.Json | ConvertFrom-Json
                } catch {
                    Write-Output "  [$formatLabel] (failed to parse status JSON: $($_.Exception.Message))"
                    continue
                }
                $totalDone += [int]$d.done
                $totalAll  += [int]$d.total
                if ($d.error) { $anyError = $true }
                Write-StatusEntry $d $formatLabel
            }
        } elseif (-not $snap -or $snap.SshFailed) {
            # Distinct from the "no status file yet" case below -- this means
            # ssh itself failed (host down, connection refused, etc), a real
            # problem worth investigating, not just "still warming up."
            Write-Output "*** UNREACHABLE (ssh failed) ***"
        } else {
            # tournament.rb only writes elo_status_*.json every
            # ELO_PROGRESS_INTERVAL (default 25) completed battles -- a
            # freshly launched/restarted shard can legitimately show this
            # for ~100s+ before its first checkpoint. Not an error by
            # itself; check whether "attempting" below is moving.
            Write-Output "(no status file yet -- normal until the first 25-battle checkpoint)"
        }

        if ($attemptingRaw -and $attemptingRaw -ne $lastAttempting[$i]) {
            $lastAttempting[$i] = $attemptingRaw
            $lastAttemptingChangedAt[$i] = Get-Date
            $entries = @()
            foreach ($blob in (Split-AttemptingBlobs $attemptingRaw)) {
                try { $entries += ($blob | ConvertFrom-Json) } catch {}
            }
            $lastAttemptingEntries[$i] = $entries
        }
        if ($lastAttempting[$i]) {
            $sinceChange = [int]((Get-Date) - $lastAttemptingChangedAt[$i]).TotalSeconds
            Write-Output "attempting (unchanged ${sinceChange}s):"
            foreach ($a in $lastAttemptingEntries[$i]) { Write-AttemptingEntry $a }
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
