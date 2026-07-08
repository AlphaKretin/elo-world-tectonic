# Launches remote_run_tournament.sh on every droplet in remote_hosts.txt,
# each with ShardIndex = its position in the file (0-based) and
# ShardCount = total host count -- mirrors run_parallel.ps1's local
# ShardIndex/ShardCount contract exactly (tournament.rb's pairing-pool
# partition is purely `i % SHARD_COUNT == SHARD_INDEX`, agnostic to
# whether shards run on one machine or across a fleet). The actual
# (format, chunk) queue-building math (below) is shared verbatim with
# run_parallel.ps1 via _chunk_queue.ps1, so the two backends can't
# silently diverge on it -- only the dispatch mechanism (ssh vs local
# Start-Process, in _remote_chunk_launch.ps1/_local_chunk_launch.ps1) and
# the aliveness check (ssh/pgrep vs a local process handle, in this
# script vs supervise_local_chunks.ps1) actually differ.
#
# Each launch is `setsid ... & disown` over a single non-interactive ssh
# call so it survives the ssh session closing -- see
# [[feedback-cross-tool-environment-gotchas]] on why plain `&disown`
# alone isn't enough (no controlling-terminal SIGHUP without setsid).
#
# Run setup_remote_shards.ps1 first. Doesn't archive each droplet's local
# errorlog.txt (~/elo-test/errorlog.txt) the way archive_run.ps1 does for
# the Windows AppData one -- those accumulate per-droplet and aren't
# pulled automatically; check via ssh if investigating a specific shard's
# errors.
#
# -Formats takes a comma-separated sequence, e.g. "singles,doubles". With
# only one format and -ChunksPerHost 1 (both defaults), this is a plain
# static launch: each host gets one persistent chunk, no supervisor, no
# queue-state file, nothing depends on this control machine staying up.
#
# Whenever there's more than one format, or -ChunksPerHost > 1, every
# dispatch goes through a flat, priority-ordered work queue instead: every
# (format, chunk) pair -- format-major, chunk-minor -- e.g. every singles
# chunk before any doubles chunk, before any singles_uncursed chunk, and so
# on. A background supervisor (supervise_remote_chunks.ps1) pops the front
# of that queue for whichever host frees up next. This gets you "one
# complete format's dataset as soon as possible" for free, with no
# explicit barrier: since every singles item sits ahead of every doubles
# item, nothing pops a doubles job while any singles item is still
# unclaimed, but a host doesn't sit idle waiting for some other slow host
# to actually finish its own singles chunk either -- it just moves on to
# whatever's next in the queue. Each dispatch is single-format (never a
# comma-joined list), so there's never a recompile between formats inside
# one job -- that used to happen on every format switch, but was never
# actually required (curse-stripping is a runtime ELO_FORMAT check, not
# compile-time -- see tournament.rb's UNCURSED_RUN), so it's not done here
# at all. If you push a code fix mid-run, kill and relaunch to pick it up.
# This does make chunk/queue progress (though not the droplets' own
# in-flight battles) depend on this control machine staying up; see
# supervise_remote_chunks.ps1's header for the exact failure mode if it
# isn't.
#
# -SubsetTrainerLabels (comma-separated trainer labels) restricts every
# chunk to only pairings touching at least one given label -- see
# tournament.rb's SUBSET_TRAINER_LABELS and analysis/apply_subset_rerun.py.
# Tags every result/status file with "_$SubsetTag" (default "subset") so
# this partial run never collides with the format's own full-round-robin
# files.
#
# -ChunksPerFormat overrides -ChunksPerHost's chunk count for specific
# formats, e.g. "singles_uncursed=3,doubles_uncursed=3" -- an uncursed
# subset rerun can have an order of magnitude fewer pairs than its cursed
# counterpart (most trainers' uncursed team is identical to their cursed
# one and gets skipped entirely), so splitting it into the same chunk
# count as singles/doubles leaves each chunk with only a handful of
# battles -- not enough to ever hit even one PROGRESS_INTERVAL status
# checkpoint, and paying a full Xvfb/Game.exe cold start for a few
# battles' worth of work. Any format not named here keeps using
# $ChunksPerHost * hosts.Count, unchanged.
param(
    [string]$Formats = "singles",
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt"),
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$PollIntervalSeconds = 5,
    [int]$SampleGamesPerTrainer = 0,
    [int]$SampleSeed = 1,
    [int]$ChunksPerHost = 1,
    [string]$ChunksPerFormat = "",
    [string]$SubsetTrainerLabels = "",
    [string]$SubsetPairsPath = "",
    [string]$SubsetTag = "subset",
    [int]$TurnTimeout = 0
)

. (Join-Path $PSScriptRoot "_chunk_queue.ps1")
. (Join-Path $PSScriptRoot "_remote_chunk_launch.ps1")

$hosts = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hosts) {
    Write-Output "No hosts found in $HostsFile"
    return
}

$ResultsDir = Join-Path (Split-Path -Parent $PSScriptRoot) "results\remote"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null
$QueueStatePath = Join-Path $ResultsDir "remote_chunk_queue.json"
$LogPath = Join-Path $ResultsDir "remote_chunk_supervisor.log"

$formatList = Get-FormatList $Formats

if ($formatList.Count -le 1 -and $ChunksPerHost -le 1) {
    Write-Output "Launching watchdogs (format: $Formats) on $($hosts.Count) droplet(s), one static chunk each, no supervisor..."
    for ($i = 0; $i -lt $hosts.Count; $i++) {
        Write-Output "[shard $i / $($hosts[$i])] launching chunk $i..."
        Invoke-RemoteChunkLaunch -TargetHost $hosts[$i] -ShardIndex $i -ShardCount $hosts.Count -Formats $Formats `
            -TurnStallTimeoutSeconds $TurnStallTimeoutSeconds -BattleStallTimeoutSeconds $BattleStallTimeoutSeconds `
            -PollIntervalSeconds $PollIntervalSeconds -SampleGamesPerTrainer $SampleGamesPerTrainer -SampleSeed $SampleSeed `
            -SubsetTrainerLabels $SubsetTrainerLabels -SubsetPairsPath $SubsetPairsPath -SubsetTag $SubsetTag -TurnTimeout $TurnTimeout
    }
    Write-Output ""
    Write-Output "$($hosts.Count) shard watchdog(s) launched. Use watch_remote_tournament.ps1 for aggregate live status."
    return
}

# format=count,format=count -- e.g. "singles_uncursed=3,doubles_uncursed=3".
# Any format not named here falls back to $ChunksPerHost * hosts.Count.
$defaultChunkCount = $hosts.Count * $ChunksPerHost
$built = New-ChunkQueue -FormatList $formatList -DefaultChunkCount $defaultChunkCount -ChunksPerFormatOverride $ChunksPerFormat
$chunkCountByFormat = $built.chunkCountByFormat
# List[object], not a plain array -- RemoveAt(0) below is O(1) amortized
# for repeated front-removal, unlike Select-Object -Skip 1 on a real array.
# .ToArray() (not @($queue)) when this needs to become a JSON-serializable
# array -- on this PS 7.6.3/.NET 10 combination, @() directly around a
# List[object] throws "Argument types do not match" for reasons that look
# like a runtime bug, not anything about this code; ToArray() sidesteps it.
$queue = $built.queue

$chunkCountSummary = Get-ChunkCountSummary -FormatList $formatList -ChunkCountByFormat $chunkCountByFormat
Write-Output "Launching watchdogs across $($hosts.Count) droplet(s), $($queue.Count) total work item(s) (chunk counts: $chunkCountSummary; format-major queue: $($formatList -join ' -> '))..."

$hostStates = @()
for ($i = 0; $i -lt $hosts.Count; $i++) {
    $item = $queue[0]
    $queue.RemoveAt(0)
    Write-Output "[shard $i / $($hosts[$i])] launching $($item.format) chunk $($item.chunk)..."
    Invoke-RemoteChunkLaunch -TargetHost $hosts[$i] -ShardIndex ([int]$item.chunk) -ShardCount $chunkCountByFormat[$item.format] -Formats $item.format `
        -TurnStallTimeoutSeconds $TurnStallTimeoutSeconds -BattleStallTimeoutSeconds $BattleStallTimeoutSeconds `
        -PollIntervalSeconds $PollIntervalSeconds -SampleGamesPerTrainer $SampleGamesPerTrainer -SampleSeed $SampleSeed `
        -SubsetTrainerLabels $SubsetTrainerLabels -SubsetPairsPath $SubsetPairsPath -SubsetTag $SubsetTag -TurnTimeout $TurnTimeout
    $hostStates += [PSCustomObject]@{ index = $i; host = $hosts[$i]; currentFormat = $item.format; currentChunk = $item.chunk; done = $false }
}

Write-Output ""
Write-Output "$($hosts.Count) shard watchdog(s) launched. Use watch_remote_tournament.ps1 for aggregate live status."

$state = [PSCustomObject]@{
    chunkCountByFormat        = $chunkCountByFormat
    formats                   = $Formats
    turnStallTimeoutSeconds   = $TurnStallTimeoutSeconds
    battleStallTimeoutSeconds = $BattleStallTimeoutSeconds
    pollIntervalSeconds       = $PollIntervalSeconds
    sampleGamesPerTrainer     = $SampleGamesPerTrainer
    sampleSeed                = $SampleSeed
    subsetTrainerLabels       = $SubsetTrainerLabels
    subsetPairsPath           = $SubsetPairsPath
    subsetTag                 = $SubsetTag
    turnTimeout               = $TurnTimeout
    pendingQueue              = $queue.ToArray()
    hosts                     = $hostStates
    updatedAt                 = (Get-Date -Format o)
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Path $QueueStatePath

# Relaunch via this same session's own executable (not a hardcoded "pwsh"/
# "powershell" name) -- short-name resolution for pwsh has been flaky in
# scripted/non-interactive contexts (see [[feedback-cross-tool-environment-gotchas]]),
# so using whatever's actually running this script sidesteps that entirely.
$currentExe = (Get-Process -Id $PID).Path
$supervisorScript = Join-Path $PSScriptRoot "supervise_remote_chunks.ps1"
$argLine = "-NoProfile -File `"$supervisorScript`" -QueueStatePath `"$QueueStatePath`" -LogPath `"$LogPath`""
$proc = Start-Process -FilePath $currentExe -WindowStyle Hidden -ArgumentList $argLine -PassThru

Write-Output "Supervisor started in the background (PID $($proc.Id); $($queue.Count) item(s) still queued after the initial launch, $($hosts.Count) hosts)."
Write-Output "  Queue state: $QueueStatePath"
Write-Output "  Supervisor log: $LogPath"
