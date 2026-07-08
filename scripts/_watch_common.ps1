# Shared rendering/aggregation for every "watch a running tournament"
# script (watch_parallel_tournament.ps1, watch_custom_trainer.ps1,
# watch_remote_tournament.ps1). Dot-sourced by all three so a
# display/aggregation fix (e.g. the global_total-based denominator, or the
# finished/error state label) only has to be made once -- before this file
# existed, each watcher (plus the now-removed single-process
# watch_tournament.ps1) had copy-pasted its own slightly-diverged version of
# the same done/total regex-scrape, and one had a structurally different
# (and better) JSON-based version that never made it back into the others.
#
# Every status file tournament.rb/custom_trainer_battles.rb write is plain
# JSON (json_encode), so all of these operate on the parsed object, not
# raw text -- regex-scraping was never necessary, just how the older
# scripts happened to be written.

# Extracts the format label / chunk index embedded in a status or
# attempting file name written by tournament.rb (writeStatus/writeAttempting
# in ELO Tournament/tournament.rb) -- elo_status_<format>_shard<N>.json /
# elo_attempting_<format>_shard<N>.json. Shared by every watcher that globs
# across multiple formats' files instead of assuming one fixed -Format
# (watch_remote_tournament.ps1, watch_parallel_tournament.ps1) -- since
# run_tournament.ps1's chunking (-GameDirIndex vs -ShardIndex/-ShardCount)
# means "_shard<N>" is a pairing-pool chunk index, not necessarily a
# physical shard/host slot, both watchers need the same parsing rather than
# each re-deriving their own regex.
function Get-ShardFormatLabel([string]$path) {
    if ($path -match 'elo_(?:status|attempting)_(.+)_shard\d+\.json$') { return $Matches[1] }
    return $path
}
function Get-ShardChunkIndex([string]$path) {
    if ($path -match 'elo_(?:status|attempting)_.+_shard(\d+)\.json$') { return [int]$Matches[1] }
    return -1
}

# Renders a duration (in seconds, possibly fractional) as [Dd] HH:MM:SS.
function Format-Duration($seconds) {
    if ($null -eq $seconds) { return "n/a" }
    $ts = [TimeSpan]::FromSeconds([double]$seconds)
    if ($ts.Days -ne 0) { return "{0}d {1:D2}:{2:D2}:{3:D2}" -f $ts.Days, [Math]::Abs($ts.Hours), [Math]::Abs($ts.Minutes), [Math]::Abs($ts.Seconds) }
    return "{0:D2}:{1:D2}:{2:D2}" -f $ts.Hours, $ts.Minutes, $ts.Seconds
}

# Parses one status file's raw text into the standard shape, or $null if
# missing/unparseable (caller decides how to report that).
function Read-StatusJson([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    try {
        return (Get-Content $path -Raw) | ConvertFrom-Json
    } catch {
        return $null
    }
}

# Prints one status entry -- shared by every watcher regardless of whether
# it came from a local file or an SSH-fetched blob.
function Show-StatusEntry([PSCustomObject]$d, [string]$label) {
    $state = if ($d.error) { "ERROR" } elseif ($d.finished) { "FINISHED" } else { "running" }
    Write-Output "  [$label] $state -- $($d.done)/$($d.total) ($($d.percent)%)"
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

# Folds one status entry into the running aggregate. $globalTotalByFormat
# and $doneByFormat are hashtables (label -> total / label -> done) the
# caller owns and resets once per refresh. global_total is the same value
# across every shard of a given format (the full pre-shard-split pair
# count), so the right denominator is "one value per format, summed", not
# "every shard's own total, summed" (which undercounts for as long as any
# shard/chunk hasn't started yet -- see watch_remote_tournament.ps1's
# -Formats header comment for the bug history this replaces). Falls back
# to `total` for status files written before global_total existed.
function Add-StatusToAggregate {
    param(
        [Parameter(Mandatory)][PSCustomObject]$Data,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][hashtable]$GlobalTotalByFormat,
        [Parameter(Mandatory)][hashtable]$DoneByFormat,
        [Parameter(Mandatory)][ref]$AnyError
    )
    $prevDone = if ($DoneByFormat.ContainsKey($Label)) { $DoneByFormat[$Label] } else { 0 }
    $DoneByFormat[$Label] = $prevDone + [int]$Data.done
    $gt = if ($null -ne $Data.global_total) { [int]$Data.global_total } else { [int]$Data.total }
    $prevTotal = if ($GlobalTotalByFormat.ContainsKey($Label)) { $GlobalTotalByFormat[$Label] } else { 0 }
    $GlobalTotalByFormat[$Label] = [Math]::Max($prevTotal, $gt)
    if ($Data.error) { $AnyError.Value = $true }
}

# A format that's fully done (summed done across every chunk seen this
# refresh >= its global_total) drops out of the live tally entirely,
# rather than staying lumped in with whatever format comes next -- a
# combined sum across formats also isn't shown even while more than one
# format is genuinely active at once (mid-transition, e.g. some hosts
# still on singles while others have already moved to doubles): summing
# singles-near-done with doubles-just-started makes it impossible to tell
# from the total alone whether singles is actually close to finished, or
# whether the move to doubles is even correct yet. Each active format
# gets its own line instead, so that judgment never has to be made blind.
function Write-AggregateFooter([hashtable]$doneByFormat, [hashtable]$globalTotalByFormat, [bool]$anyError) {
    Write-Output ""
    Write-Output "================================================================"
    $completed = @()
    $active = @()
    foreach ($label in $globalTotalByFormat.Keys) {
        $total = $globalTotalByFormat[$label]
        $done = if ($doneByFormat.ContainsKey($label)) { $doneByFormat[$label] } else { 0 }
        if ($total -gt 0 -and $done -ge $total) {
            $completed += "$label ($done/$total)"
        } else {
            $active += [PSCustomObject]@{ Label = $label; Done = $done; Total = $total }
        }
    }
    if ($completed.Count -gt 0) {
        Write-Output "COMPLETE: $($completed -join ', ')"
    }
    if ($active.Count -gt 0) {
        foreach ($a in ($active | Sort-Object Label)) {
            $pct = if ($a.Total -gt 0) { [math]::Round($a.Done * 100.0 / $a.Total, 3) } else { 0 }
            Write-Output "AGGREGATE [$($a.Label)]: $($a.Done) / $($a.Total) ($pct%)"
        }
    } elseif ($completed.Count -eq 0) {
        Write-Output "AGGREGATE: no status seen yet."
    }
    if ($anyError) {
        Write-Output "*** At least one shard reports a top-level error -- check its status above. ***"
    }
    Write-Output "Last refreshed: $(Get-Date -Format o)"
}
