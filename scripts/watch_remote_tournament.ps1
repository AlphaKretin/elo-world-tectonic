# Aggregate live status across every remote shard, polled over SSH.
# Mirrors watch_parallel_tournament.ps1's display, but fetches each
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
#
# -Formats optionally narrows both the display and the AGGREGATE line to
# just the given exact format label(s) (comma-separated, e.g.
# "singles_subset,doubles_subset") -- otherwise every elo_status_*_shard*.json
# a host has ever produced gets summed in, including a long-finished full
# round robin's files left over from a previous run. That's not wrong
# (each file's own done/total is correctly scoped to its own pairs), but
# it means the AGGREGATE line silently mixes two logically separate runs'
# totals -- e.g. watching a small subset rerun on a droplet that also has
# the old full-format run's finished status files sitting on disk makes
# AGGREGATE jump to ~99%+ instantly, dwarfed by the old finished total.
# Use -Formats to scope the view down to just the run you're actually
# watching.
#
# -QueueStatePath defaults to run_remote_parallel.ps1's own default
# (results\remote\remote_chunk_queue.json) so a supervised/chunked run's
# AGGREGATE is accurate with zero extra flags: supervise_remote_chunks.ps1
# deletes a finished chunk's status file the moment its host picks up the
# next one (to stop stale FINISHED entries from stacking up here), which
# would otherwise mean AGGREGATE can only ever reflect chunks currently in
# flight and never real total progress. That script instead banks each
# finished chunk's done count into the state file's completedByFormat
# before deleting, and this watcher adds it back in as a baseline. Safe to
# point at a nonexistent/unrelated path (or a plain unchunked run with no
# supervisor) -- just no baseline gets added, same as before this existed.
param(
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt"),
    [int]$RefreshSeconds = 5,
    [string]$Formats = "",
    [string]$QueueStatePath = (Join-Path (Split-Path -Parent $PSScriptRoot) "results\remote\remote_chunk_queue.json")
)

. (Join-Path $PSScriptRoot "_watch_common.ps1")

$formatFilter = @($Formats -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })

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

# Get-ShardFormatLabel, Format-Duration, and Show-StatusEntry come from
# _watch_common.ps1 -- shared with every other watch_*.ps1 script.

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
        $remoteCmd = "for f in ~/elo-test/results/elo_status_*_shard*.json; do [ -f `"`$f`" ] && echo `"`$f:`" && cat `"`$f`"; done 2>/dev/null; echo '---ATTEMPTING---'; for f in ~/elo-test/results/elo_attempting_*_shard*.json; do [ -f `"`$f`" ] && cat `"`$f`"; done 2>/dev/null; echo '---HEARTBEAT---'; for f in ~/elo-test/results/elo_turn_heartbeat_*_shard*.json; do [ -f `"`$f`" ] && echo `"`$f:`" && cat `"`$f`"; done 2>/dev/null"
        # -n: see setup_remote_shards.ps1's comment on the same flag.
        $output = & ssh -n -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$thisHost" $remoteCmd 2>$null
        [PSCustomObject]@{ HostName = $thisHost; Output = ($output -join "`n"); SshFailed = ($LASTEXITCODE -ne 0) }
    }

    # try/catch: Clear-Host throws "handle is invalid" when stdout isn't a
    # real interactive console (e.g. output redirected to a file/log) --
    # harmless to skip in that case, just less pretty.
    try { Clear-Host } catch {}
    $scopeLabel = if ($formatFilter) { "formats: $($formatFilter -join ', ')" } else { "all formats" }
    Write-Output "ELO Tournament remote status ($scopeLabel, $($hostList.Count) droplets) -- Ctrl+C to stop watching (does not stop the tournament)"
    Write-Output "================================================================"

    # Keyed by format label, not summed per-blob -- see _watch_common.ps1's
    # Add-StatusToAggregate for why (global_total is the same value across
    # every shard/chunk of a given format, so it's added once per format
    # seen, not once per shard -- the mirror-image fix to the stale-total
    # bug this -Formats filter above was originally built to guard against).
    $doneByFormat = @{}
    $globalTotalByFormat = @{}
    $anyError  = $false

    # Completed-chunk totals persisted by supervise_remote_chunks.ps1's
    # completedByFormat (folded in there right before a finished chunk's
    # status file is deleted -- see that script's rm -f). Seeded here
    # first so the per-host loop below adds live in-flight progress on top
    # via Add-StatusToAggregate's own prevDone + done accumulation; without
    # this the aggregate could only ever reflect chunks currently running,
    # never a finished chunk's real, already-banked progress. Missing/
    # unparseable file (no supervisor ever ran this queue, e.g. a plain
    # unchunked launch) just means no baseline to add -- same as today.
    if (Test-Path $QueueStatePath) {
        try {
            $queueState = Get-Content $QueueStatePath -Raw | ConvertFrom-Json
            if ($queueState.completedByFormat) {
                foreach ($prop in $queueState.completedByFormat.PSObject.Properties) {
                    if (-not $formatFilter -or $formatFilter -contains $prop.Name) {
                        $doneByFormat[$prop.Name] = [int]$prop.Value
                    }
                }
            }
        } catch {
            # Corrupt/mid-write state file -- skip this refresh's baseline
            # rather than crashing the whole watcher; try again next poll.
        }
    }

    for ($i = 0; $i -lt $hostList.Count; $i++) {
        $thisHost = $hostList[$i]
        $snap = $snapshots | Where-Object { $_.HostName -eq $thisHost } | Select-Object -First 1
        $parts = if ($snap) { $snap.Output -split "---ATTEMPTING---" } else { @("", "") }
        $statusRaw = $parts[0].Trim()
        $attemptingParts = if ($parts.Count -gt 1) { $parts[1] -split "---HEARTBEAT---" } else { @("", "") }
        $attemptingRaw = $attemptingParts[0].Trim()
        $heartbeatRaw = if ($attemptingParts.Count -gt 1) { $attemptingParts[1].Trim() } else { "" }

        Write-Output ""
        Write-Output "-- shard $i ($thisHost) --"
        $statusBlobs = if ($statusRaw) { Split-StatusBlobs $statusRaw } else { @() }
        if ($formatFilter) {
            $statusBlobs = @($statusBlobs | Where-Object { $formatFilter -contains (Get-ShardFormatLabel $_.Path) })
        }
        if ($statusBlobs) {
            $parsed = @()
            foreach ($blob in $statusBlobs) {
                $formatLabel = Get-ShardFormatLabel $blob.Path
                try {
                    $d = $blob.Json | ConvertFrom-Json
                } catch {
                    Write-Output "  [$formatLabel] (failed to parse status JSON: $($_.Exception.Message))"
                    continue
                }
                # Always fold every format this shard has ever produced into
                # the running totals -- a finished singles file is still real
                # progress even once doubles has taken over the display.
                Add-StatusToAggregate -Data $d -Label $formatLabel -GlobalTotalByFormat $globalTotalByFormat `
                    -DoneByFormat $doneByFormat -AnyError ([ref]$anyError)
                $parsed += [PSCustomObject]@{ Label = $formatLabel; Data = $d }
            }
            # Without -Formats, a shard part-way through its format sequence
            # accumulates one status file per format it's passed through
            # (singles finished, doubles running, ...) and the view just
            # grows forever, mostly showing stale finished formats. Only the
            # most recently updated one is what's actually happening now, so
            # collapse the *display* down to that -- the totals above already
            # counted everything regardless.
            $toShow = if (-not $formatFilter -and $parsed.Count -gt 1) {
                @($parsed | Sort-Object { [datetime]$_.Data.updated_at } -Descending | Select-Object -First 1)
            } else {
                $parsed
            }
            foreach ($p in $toShow) { Show-StatusEntry $p.Data $p.Label }
        } elseif (-not $snap -or $snap.SshFailed) {
            # Checked before the formatFilter-specific message below -- ssh
            # itself failing (host down, connection refused, etc) is a real
            # problem worth investigating regardless of which format(s)
            # this view is scoped to, not just "still warming up."
            Write-Output "*** UNREACHABLE (ssh failed) ***"
        } elseif ($formatFilter) {
            Write-Output "(no status file yet for $($formatFilter -join ', ') -- normal until the first checkpoint)"
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
            $shownEntries = if ($formatFilter) {
                @($lastAttemptingEntries[$i] | Where-Object { $formatFilter -contains $_.format })
            } else {
                $lastAttemptingEntries[$i]
            }
            if ($shownEntries) {
                $sinceChange = [int]((Get-Date) - $lastAttemptingChangedAt[$i]).TotalSeconds
                Write-Output "attempting (unchanged ${sinceChange}s):"
                foreach ($a in $shownEntries) { Write-AttemptingEntry $a }
            }
        }

        # Heartbeat carries its own updated_at (unlike attempting), so no
        # local change-tracking needed -- just pick whichever format's
        # heartbeat is freshest, same collapse-to-latest logic as the
        # status blobs above.
        $heartbeatBlobs = if ($heartbeatRaw) { Split-StatusBlobs $heartbeatRaw } else { @() }
        if ($formatFilter) {
            $heartbeatBlobs = @($heartbeatBlobs | Where-Object { $formatFilter -contains (Get-ShardFormatLabel $_.Path) })
        }
        if ($heartbeatBlobs) {
            $hbParsed = @()
            foreach ($blob in $heartbeatBlobs) {
                try { $hbParsed += [PSCustomObject]@{ Label = (Get-ShardFormatLabel $blob.Path); Data = ($blob.Json | ConvertFrom-Json) } } catch {}
            }
            $hbToShow = if (-not $formatFilter -and $hbParsed.Count -gt 1) {
                @($hbParsed | Sort-Object { [datetime]$_.Data.updated_at } -Descending | Select-Object -First 1)
            } else {
                $hbParsed
            }
            foreach ($p in $hbToShow) {
                $line = Format-HeartbeatLine $p.Data $p.Label
                if ($line) { Write-Output $line }
            }
        }
    }

    Write-AggregateFooter $doneByFormat $globalTotalByFormat $anyError

    Start-Sleep -Seconds $RefreshSeconds
}
