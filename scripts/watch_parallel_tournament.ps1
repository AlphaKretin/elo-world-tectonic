# Aggregate live status across every local shard's status files. Renamed
# from watch_tournament_parallel.ps1 to match watch_remote_tournament.ps1's
# naming convention, and its display mirrors that script's structure: one
# block per physical shard (like remote's one block per host), not one
# block per format -- a wall of finished/superseded format sections was
# exactly Luna's "way more cluttered and less useful" complaint (confirmed
# live 2026-07-08).
#
# Unlike the remote watcher, every local shard directory's status/attempting
# files already live in one shared results/ folder -- no per-host SSH
# round-trip, and so no Split-StatusBlobs/Split-AttemptingBlobs-style
# concatenation parsing either, since each file is already discrete rather
# than several files pasted back-to-back over one SSH stream.
#
# A status file's "_shard<N>" suffix is a pairing-pool chunk index, not
# necessarily the physical shards\shardN directory that produced it --
# run_parallel.ps1's supervisor freely reassigns whichever physical shard
# frees up next to whatever (format, chunk) is next in the queue. So
# grouping by physical shard (what Luna actually wants, to match remote's
# per-host view) needs an explicit lookup: Get-CurrentShardAssignments reads
# supervise_local_chunks.ps1's own reassignment state (local_chunk_queue.json
# -- shards[].currentFormat/currentChunk) to answer "what is shard i doing
# right now", rather than inventing a second source of truth (e.g. a new
# field threaded through tournament.rb's own status JSON). Falls back to
# "chunk index == physical shard" when no queue-state file exists, which is
# exactly true for run_parallel.ps1's static (single-format, unchunked)
# dispatch path (no supervisor ever runs, so no reassignment is possible).
#
# The aggregate/COMPLETE totals still fold in EVERY status file that exists
# for a format, not just whichever chunk currently sits on a live shard --
# a chunk whose shard has since moved on to other work is still real,
# already-counted progress.
#
# -Formats optionally narrows both the display and the AGGREGATE line to
# just the given exact format label(s) (comma-separated, e.g.
# "singles_subset,doubles_subset") -- same reasoning as
# watch_remote_tournament.ps1's -Formats: without it, a long-finished
# format's leftover status files from a previous run stay folded into the
# totals forever. Default (empty) shows every format any status file exists
# for.
param(
    [string]$Formats = "",
    [int]$RefreshSeconds = 3
)

. (Join-Path $PSScriptRoot "_watch_common.ps1")

$RepoRoot       = Split-Path -Parent $PSScriptRoot
$ResultsDir     = Join-Path $RepoRoot "results"
$QueueStatePath = Join-Path $ResultsDir "local_chunk_queue.json"
$formatFilter   = @($Formats -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })

$lastAttempting          = @{}
$lastAttemptingChangedAt = @{}

# Returns @{ Shards = @(sorted [PSCustomObject]{Index, Label, Chunk, Done}); FromQueueState = [bool] }.
# currentFormat in the queue state is the raw format name (e.g. "singles"),
# not the subset-tag-suffixed label status files are keyed by (e.g.
# "singles_timeout_rerun") -- reconstruct the same suffix
# Invoke-TournamentFormat applies (run_tournament.ps1) from the queue
# state's own subsetTrainerLabels/subsetPairsPath/subsetTag fields so the
# lookup key actually matches.
function Get-CurrentShardAssignments {
    if (Test-Path $QueueStatePath) {
        try {
            $state = Get-Content $QueueStatePath -Raw | ConvertFrom-Json
            $hasSubset = [bool]($state.subsetTrainerLabels -or $state.subsetPairsPath)
            $shards = @($state.shards | ForEach-Object {
                $label = if (-not $_.currentFormat) { $null } elseif ($hasSubset) { "$($_.currentFormat)_$($state.subsetTag)" } else { $_.currentFormat }
                [PSCustomObject]@{ Index = [int]$_.index; Label = $label; Chunk = $_.currentChunk; Done = [bool]$_.done }
            } | Sort-Object Index)
            return [PSCustomObject]@{ Shards = $shards; FromQueueState = $true }
        } catch {
            # fall through to the no-queue-state fallback below
        }
    }
    # No supervisor ever ran (run_parallel.ps1's static single-format,
    # unchunked path) -- chunk index IS the physical shard index there, so
    # derive the shard list straight from whatever status files exist.
    $shards = @(Get-ChildItem -Path $ResultsDir -Filter "elo_status_*_shard*.json" -ErrorAction SilentlyContinue |
        ForEach-Object {
            [PSCustomObject]@{ Index = (Get-ShardChunkIndex $_.Name); Label = (Get-ShardFormatLabel $_.Name); Chunk = (Get-ShardChunkIndex $_.Name); Done = $false }
        } | Sort-Object Index -Unique)
    return [PSCustomObject]@{ Shards = $shards; FromQueueState = $false }
}

while ($true) {
    $assignments = Get-CurrentShardAssignments
    $shards      = $assignments.Shards

    # try/catch: Clear-Host throws "handle is invalid" when stdout isn't a
    # real interactive console (e.g. output redirected to a file/log) --
    # harmless to skip in that case, just less pretty.
    try { Clear-Host } catch {}
    $scopeLabel = if ($formatFilter) { "formats: $($formatFilter -join ', ')" } else { "all formats" }
    Write-Output "ELO Tournament parallel status ($scopeLabel, $($shards.Count) local shard(s)) -- Ctrl+C to stop watching (does not stop the tournament)"
    Write-Output "================================================================"

    $doneByFormat        = @{}
    $globalTotalByFormat = @{}
    $anyError            = $false

    # Aggregate/COMPLETE totals fold in every status file for every format,
    # independent of which physical shard currently owns that (format,
    # chunk) -- a chunk whose shard has since moved on is still real,
    # already-counted progress (see this file's header).
    $allStatusFiles = @(Get-ChildItem -Path $ResultsDir -Filter "elo_status_*_shard*.json" -ErrorAction SilentlyContinue)
    foreach ($f in $allStatusFiles) {
        $label = Get-ShardFormatLabel $f.Name
        if ($formatFilter -and ($formatFilter -notcontains $label)) { continue }
        $d = Read-StatusJson $f.FullName
        if ($d) {
            Add-StatusToAggregate -Data $d -Label $label -GlobalTotalByFormat $globalTotalByFormat `
                -DoneByFormat $doneByFormat -AnyError ([ref]$anyError)
        }
    }

    if ($shards.Count -eq 0) {
        Write-Output ""
        Write-Output "(no status files yet -- normal until the first 25-battle checkpoint)"
    }

    foreach ($s in $shards) {
        if ($formatFilter -and $s.Label -and ($formatFilter -notcontains $s.Label)) { continue }

        Write-Output ""
        Write-Output "-- shard $($s.Index) --"

        if (-not $s.Label) {
            if ($s.Done) { Write-Output "  (idle -- queue exhausted)" } else { Write-Output "  (no status file yet -- normal until the first checkpoint)" }
            continue
        }

        $statusPath = Join-Path $ResultsDir "elo_status_$($s.Label)_shard$($s.Chunk).json"
        $d = Read-StatusJson $statusPath
        $chunkDesc = "$($s.Label) chunk $($s.Chunk)"
        if (-not $d) {
            Write-Output "  [$chunkDesc] (no status file yet -- normal until the first checkpoint)"
        } elseif ($d.error) {
            Write-Output "  [$chunkDesc] ERROR -- $($d.done)/$($d.total) ($($d.percent)%)"
            Write-Output "    *** ERROR: $($d.error.error_class): $($d.error.error_message) ***"
        } else {
            Show-StatusEntry $d $chunkDesc
        }

        $attemptingPath = Join-Path $ResultsDir "elo_attempting_$($s.Label)_shard$($s.Chunk).json"
        if (Test-Path $attemptingPath) {
            $current = Get-Content $attemptingPath -Raw
            $key = "shard$($s.Index)"
            if ($current -ne $lastAttempting[$key]) {
                $lastAttempting[$key]          = $current
                $lastAttemptingChangedAt[$key] = Get-Date
            }
            $sinceChange = [int]((Get-Date) - $lastAttemptingChangedAt[$key]).TotalSeconds
            try {
                $a = $lastAttempting[$key] | ConvertFrom-Json
                Write-Output "  attempting (unchanged ${sinceChange}s): $($a.trainer1) vs $($a.trainer2) (seed $($a.seed))"
            } catch {
                Write-Output "  attempting (unchanged ${sinceChange}s): $($lastAttempting[$key])"
            }
        }
    }

    Write-AggregateFooter $doneByFormat $globalTotalByFormat $anyError

    Start-Sleep -Seconds $RefreshSeconds
}
