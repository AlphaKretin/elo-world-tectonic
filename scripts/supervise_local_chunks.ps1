# Background loop that hands out remaining local chunk work items (see
# run_parallel.ps1's -ChunksPerShard/-ChunksPerFormat) to whichever shard
# directory frees up first, instead of leaving a fast shard idle while a
# slow shard works through its own static share. Mirrors
# supervise_remote_chunks.ps1's structure and correctness requirements
# exactly (see that script's header for the full rationale on the flat
# format-major queue) -- the one real difference is how "is this chunk
# still running" gets checked: this machine has the actual local process
# handle for each shard's watchdog, so it's a direct Get-Process lookup,
# not an ssh/pgrep round-trip (and so has no need for that script's
# self-match grep workaround either).
#
# Started detached (hidden window, own process) by run_parallel.ps1 right
# after it launches each shard directory's first job, same as the remote
# version. Only correctness requirement: it must be the sole thing ever
# reassigning work, since two supervisors racing on the same queue-state
# file could both claim the same front-of-queue item.
#
# All run config lives in the queue-state JSON, not in this script's own
# params -- same reasoning as supervise_remote_chunks.ps1: re-pointing this
# at an existing state file (e.g. after this process died and you restart
# it by hand) can never drift from what actually got launched.
#
# Requires this machine and this process to keep running for work to
# actually get reassigned -- if it's not running, in-flight shards simply
# finish their current chunk and then sit idle, no worse than the
# non-oversubscribed case.
param(
    [Parameter(Mandatory)][string]$QueueStatePath,
    [Parameter(Mandatory)][string]$LogPath
)

. (Join-Path $PSScriptRoot "_local_chunk_launch.ps1")

function Write-Log([string]$msg) {
    Add-Content -Path $LogPath -Value "$(Get-Date -Format o)  $msg"
}

function Save-State($state) {
    $state.updatedAt = (Get-Date -Format o)
    $state | ConvertTo-Json -Depth 5 | Set-Content -Path $QueueStatePath
}

# Not just "does a process with this PID exist" -- PIDs get recycled by
# Windows, and this loop's poll interval is easily long enough for that to
# happen between checks. Requiring the name too doesn't fully close the
# race (another shell process could theoretically reuse the PID in the
# same window) but makes it astronomically less likely for no extra cost.
#
# Checks both "pwsh" and "powershell" (not just one hardcoded name) since
# _local_chunk_launch.ps1 launches via the *calling* session's own resolved
# exe path (see its header on why: short-name resolution flakiness), which
# is PowerShell 7's pwsh.exe on this machine -- Get-Process reports that
# ProcessName as "pwsh", never "powershell". A version that only checked
# "powershell" made this always return $false regardless of the real
# process state, silently defeating the entire point of this function: the
# supervisor reassigned work onto shards whose watchdog (and Game.exe) was
# still genuinely running, producing two live processes in one shard
# directory -- exactly the collision this whole chunking design exists to
# prevent. Confirmed live 2026-07-08 (see [[project-phase-status]]).
function Test-ShardBusy($shardState) {
    if (-not $shardState.pid) { return $false }
    $proc = Get-Process -Id $shardState.pid -ErrorAction SilentlyContinue
    return [bool]($proc -and ($proc.ProcessName -eq "pwsh" -or $proc.ProcessName -eq "powershell"))
}

Write-Log "Supervisor starting (PID $PID). Queue state: $QueueStatePath"

while ($true) {
    $state = Get-Content $QueueStatePath -Raw | ConvertFrom-Json
    # ConvertFrom-Json collapses a single-element JSON array to a scalar
    # object, not a 1-element array -- @() guards every array field read
    # back from the state file against that (same gotcha as the remote
    # version).
    $pendingQueue = @($state.pendingQueue)

    $activeShards = @($state.shards | Where-Object { -not $_.done })
    if ($activeShards.Count -eq 0) {
        Write-Log "All shards done, work queue exhausted. Supervisor exiting."
        break
    }

    foreach ($s in $activeShards) {
        if (Test-ShardBusy $s) { continue }

        if ($pendingQueue.Count -gt 0) {
            $item = $pendingQueue[0]
            $pendingQueue = @($pendingQueue | Select-Object -Skip 1)
            $prevDesc = if ($s.currentFormat) { "$($s.currentFormat) chunk $($s.currentChunk)" } else { "(idle, no prior job)" }
            Write-Log "shard $($s.index) finished $prevDesc -> picking up $($item.format) chunk $($item.chunk) ($($pendingQueue.Count) item(s) left in queue)"

            $s.currentFormat = $item.format
            $s.currentChunk = $item.chunk
            # chunkCountByFormat round-trips through JSON as a
            # PSCustomObject (one property per format), not a hashtable --
            # same gotcha as the remote version.
            $chunkCountForFormat = [int]$state.chunkCountByFormat.($item.format)
            $proc = Invoke-LocalChunkLaunch -GameDirIndex $s.index -ShardIndex ([int]$item.chunk) -ShardCount $chunkCountForFormat -Formats $item.format `
                -TurnStallTimeoutSeconds $state.turnStallTimeoutSeconds -BattleStallTimeoutSeconds $state.battleStallTimeoutSeconds `
                -PollIntervalSeconds $state.pollIntervalSeconds -SampleGamesPerTrainer $state.sampleGamesPerTrainer -SampleSeed $state.sampleSeed `
                -SubsetTrainerLabels $state.subsetTrainerLabels -SubsetPairsPath $state.subsetPairsPath `
                -SubsetTag $(if ($state.subsetTag) { $state.subsetTag } else { "subset" }) -TurnTimeout $(if ($state.turnTimeout) { [int]$state.turnTimeout } else { 0 }) `
                -UseDebugFlag:([bool]$state.useDebugFlag)
            $s.pid = $proc.Id
        } else {
            Write-Log "shard $($s.index) finished $($s.currentFormat) chunk $($s.currentChunk) -- queue empty, shard idle"
            $s.done = $true
        }
        $state.pendingQueue = $pendingQueue
        Save-State $state
    }

    Start-Sleep -Seconds ([Math]::Max(5, [int]$state.pollIntervalSeconds))
}
