# Background loop that hands out remaining work items (see
# run_remote_parallel.ps1's -ChunksPerHost and multi-format queueing) to
# whichever host finishes its current job first, instead of leaving a fast
# host idle while a slow host works through its own static share -- the
# "unexpectedly slow shard" problem that's repeatedly bottlenecked full runs.
#
# The work queue is a flat, priority-ordered list of (format, chunk) pairs
# -- format-major, chunk-minor -- not "one chunk that internally marches
# through every format." This is what actually implements "finish every
# chunk of singles before any chunk of doubles starts, but don't block a
# free host from picking up doubles just because some other host is still
# slowly grinding through its own singles chunk": since every singles item
# sits ahead of every doubles item in the queue, a FIFO pop naturally
# enforces the ordering with no explicit barrier/wait logic needed. Each
# dispatch is a single-format launch (remote_run_tournament.sh --formats
# <one format>), so there's no cross-format recompile inside one job --
# recompiling between formats was never actually required for correctness
# (curse-stripping is a runtime ELO_FORMAT check, not compile-time; see
# tournament.rb's UNCURSED_RUN), it only mattered once, the very first time
# code changed mid-run, and had been needlessly recurring on every format
# switch since. Dropped entirely.
#
# Started detached (hidden window, own process) by run_remote_parallel.ps1
# right after it launches each host's first job, so the interactive
# terminal returns immediately -- this keeps running in the background,
# not tying up that terminal. Only correctness requirement: it must be the
# sole thing ever reassigning work, since two supervisors racing on the
# same queue-state file could both claim the same front-of-queue item.
#
# All run config (formats, timeouts, chunk count per format, current
# per-host assignment, the pending queue itself) lives in the queue-state
# JSON, not
# in this script's own params -- so re-pointing this at an existing state
# file (e.g. after this process died and you restart it by hand, or to
# resume a run with a hand-edited queue) can never drift from what
# actually got launched.
#
# Requires this control machine to stay up and this process to keep
# running for work to actually get reassigned -- if it's not running (or
# this machine is down), in-flight droplets simply finish their current
# job and then sit idle, no worse than the non-oversubscribed case.
param(
    [Parameter(Mandatory)][string]$QueueStatePath,
    [Parameter(Mandatory)][string]$LogPath
)

. (Join-Path $PSScriptRoot "_remote_chunk_launch.ps1")

function Write-Log([string]$msg) {
    Add-Content -Path $LogPath -Value "$(Get-Date -Format o)  $msg"
}

function Save-State($state) {
    $state.updatedAt = (Get-Date -Format o)
    $state | ConvertTo-Json -Depth 5 | Set-Content -Path $QueueStatePath
}

# Banks a finished chunk's done count into $state.completedByFormat (a
# format_tag -> cumulative-done map) so watch_remote_tournament.ps1 can add
# it back into AGGREGATE after its status file is deleted below -- without
# this, AGGREGATE can only ever reflect chunks currently in flight, since a
# finished chunk's status file never survives past this same poll cycle.
# $state.completedChunks (format_tag -> [chunk indices already folded in])
# makes this idempotent: PSCustomObject property assignment requires
# Add-Member for a not-yet-existing property, so both maps get built up
# property-by-property here rather than assumed to pre-exist -- and a
# chunk index already recorded is skipped rather than double-counted,
# which matters if this ever runs twice for the same transition (e.g. a
# crash between folding in and Save-State, then a retry next poll).
function Add-CompletedChunk($state, [string]$formatTag, [int]$chunkIndex, [int]$doneCount) {
    if (-not ($state.PSObject.Properties.Name -contains "completedByFormat")) {
        $state | Add-Member -NotePropertyName "completedByFormat" -NotePropertyValue ([PSCustomObject]@{})
    }
    if (-not ($state.PSObject.Properties.Name -contains "completedChunks")) {
        $state | Add-Member -NotePropertyName "completedChunks" -NotePropertyValue ([PSCustomObject]@{})
    }
    if (-not ($state.completedChunks.PSObject.Properties.Name -contains $formatTag)) {
        $state.completedChunks | Add-Member -NotePropertyName $formatTag -NotePropertyValue @()
    }
    $alreadyFolded = @($state.completedChunks.$formatTag)
    if ($alreadyFolded -contains $chunkIndex) { return }

    if (-not ($state.completedByFormat.PSObject.Properties.Name -contains $formatTag)) {
        $state.completedByFormat | Add-Member -NotePropertyName $formatTag -NotePropertyValue 0
    }
    $state.completedByFormat.$formatTag = [int]$state.completedByFormat.$formatTag + $doneCount
    $state.completedChunks.$formatTag = @($alreadyFolded + $chunkIndex)
}

# Shared by both "host picks up a new chunk" and "queue empty, host goes
# idle" below -- both are the same event (a host's current chunk just
# finished), differing only in whether a next job follows, so both need
# the same fold-in-before-status-file-is-gone treatment. $DeleteFiles is
# $false for the idle case: nothing will ever reassign that host again
# this run, so there's no stacking risk and the file is left as a visible
# finished marker (see the caller's own comment for why).
function Complete-Chunk($state, [PSCustomObject]$h, [bool]$DeleteFiles) {
    $subsetTag = $(if ($state.subsetTag) { $state.subsetTag } else { "subset" })
    $formatTag = if ($state.subsetTrainerLabels -or $state.subsetPairsPath) { "$($h.currentFormat)_$subsetTag" } else { $h.currentFormat }
    $suffix = "${formatTag}_shard$($h.currentChunk)"
    $statusJson = & ssh -n -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$($h.host)" `
        "cat ~/elo-test/results/elo_status_${suffix}.json 2>/dev/null"
    $done = 0
    try { $done = [int](($statusJson | Out-String | ConvertFrom-Json).done) } catch {
        Write-Log "host $($h.index) ($($h.host)) -- couldn't read final done count for finished $formatTag chunk $($h.currentChunk), banking 0 (status file may have been missing/unparseable)"
    }
    Add-CompletedChunk -state $state -formatTag $formatTag -chunkIndex ([int]$h.currentChunk) -doneCount $done

    if ($DeleteFiles) {
        & ssh -n -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$($h.host)" `
            "rm -f ~/elo-test/results/elo_status_${suffix}.json ~/elo-test/results/elo_attempting_${suffix}.json ~/elo-test/results/elo_turn_heartbeat_${suffix}.json" 2>$null
    }
}

Write-Log "Supervisor starting (PID $PID). Queue state: $QueueStatePath"

while ($true) {
    $state = Get-Content $QueueStatePath -Raw | ConvertFrom-Json
    # ConvertFrom-Json collapses a single-element JSON array to a scalar
    # object, not a 1-element array -- @() guards every array field read
    # back from the state file against that.
    $pendingQueue = @($state.pendingQueue)

    $activeHosts = @($state.hosts | Where-Object { -not $_.done })
    if ($activeHosts.Count -eq 0) {
        Write-Log "All hosts done, work queue exhausted. Supervisor exiting."
        break
    }

    foreach ($h in $activeHosts) {
        # -o ConnectTimeout=5: a hung ssh check here would otherwise stall
        # every other host's poll behind it in this same sequential loop.
        #
        # [r]emote_run_tournament.sh (not remote_run_tournament.sh): the
        # classic grep self-exclude trick. Without the brackets, this
        # exact ssh command's own remote shell process has
        # "remote_run_tournament.sh" as a literal substring of its own
        # command line, so `pgrep -f` matches itself and always reports
        # "alive" -- which is exactly what silently stalled every chunk
        # reassignment during the resolutionChoice subset rerun (chunks
        # 0-9 finished in full, chunks 10-29 never got dispatched, because
        # every host looked permanently "busy" from the moment its first
        # job launched). The bracket makes this command's own argv read
        # "[r]emote_run_tournament.sh", which does not match the regex
        # "remote_run_tournament.sh" (there's a literal "]" between the
        # "r" and "emote..." that isn't there in a real target process).
        $alive = & ssh -n -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$($h.host)" `
            "pgrep -f '[r]emote_run_tournament.sh' > /dev/null && echo alive || echo dead" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Log "host $($h.index) ($($h.host)) unreachable this poll -- will retry"
            continue
        }
        if (($alive | Select-Object -Last 1) -eq "alive") { continue }

        if ($pendingQueue.Count -gt 0) {
            $item = $pendingQueue[0]
            $pendingQueue = @($pendingQueue | Select-Object -Skip 1)
            $prevDesc = if ($h.currentFormat) { "$($h.currentFormat) chunk $($h.currentChunk)" } else { "(idle, no prior job)" }
            Write-Log "host $($h.index) ($($h.host)) finished $prevDesc -> picking up $($item.format) chunk $($item.chunk) ($($pendingQueue.Count) item(s) left in queue)"

            # A host that already had a previous job leaves that chunk's
            # status/attempting/heartbeat files sitting on disk forever --
            # it will never be reassigned that same chunk index again this
            # run, so nothing else will ever overwrite them. Left alone,
            # watch scripts glob every elo_*_shard*.json file on the host
            # and show that stale (already-FINISHED) entry indefinitely
            # alongside the genuinely current job, which is exactly the
            # "stacking" watch_remote_tournament.ps1 was supposed to avoid.
            # elo_results_*/elo_crash_streaks_* are deliberately not touched
            # here -- those hold real battle data that still needs pulling.
            if ($h.currentFormat) { Complete-Chunk -state $state -h $h -DeleteFiles $true }

            $h.currentFormat = $item.format
            $h.currentChunk = $item.chunk
            # chunkCountByFormat round-trips through JSON as a
            # PSCustomObject (one property per format), not a hashtable --
            # ConvertFrom-Json never reconstructs the hashtable
            # ConvertTo-Json was originally fed.
            $chunkCountForFormat = [int]$state.chunkCountByFormat.($item.format)
            Invoke-RemoteChunkLaunch -TargetHost $h.host -ShardIndex ([int]$item.chunk) -ShardCount $chunkCountForFormat -Formats $item.format `
                -TurnStallTimeoutSeconds $state.turnStallTimeoutSeconds -BattleStallTimeoutSeconds $state.battleStallTimeoutSeconds `
                -PollIntervalSeconds $state.pollIntervalSeconds -SampleGamesPerTrainer $state.sampleGamesPerTrainer -SampleSeed $state.sampleSeed `
                -SubsetTrainerLabels $state.subsetTrainerLabels -SubsetPairsPath $state.subsetPairsPath `
                -SubsetTag $(if ($state.subsetTag) { $state.subsetTag } else { "subset" }) -TurnTimeout $(if ($state.turnTimeout) { [int]$state.turnTimeout } else { 0 }) | Out-Null
        } else {
            Write-Log "host $($h.index) ($($h.host)) finished $($h.currentFormat) chunk $($h.currentChunk) -- queue empty, host idle"
            # Nothing will ever reassign this host again this run, so its
            # status file isn't deleted (no stacking risk -- see the
            # reassignment branch's comment above) and is left as a visible
            # finished marker. Still needs folding into completedByFormat
            # though, or this host's last chunk would silently be the one
            # chunk in the whole run AGGREGATE never counts.
            if ($h.currentFormat) { Complete-Chunk -state $state -h $h -DeleteFiles $false }
            $h.done = $true
        }
        $state.pendingQueue = $pendingQueue
        Save-State $state
    }

    Start-Sleep -Seconds ([Math]::Max(5, [int]$state.pollIntervalSeconds))
}
