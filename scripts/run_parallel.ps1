# Launches ShardCount parallel tournament watchdogs (run_tournament.ps1),
# each in its own PowerShell process against its own shard game directory
# (run setup_shards.ps1 first). Mirrors run_remote_parallel.ps1's
# structure and options as closely as a local/no-ssh backend allows -- see
# that script's header for the full design rationale on formats/chunking;
# this one just launches local Start-Process instances instead of ssh, and
# shares the actual queue-building logic via _chunk_queue.ps1 so the two
# backends can't silently diverge on it. Each shard's output streams to its
# own log under results/; this script just launches them and returns.
#
# Always archives errorlog.txt first (fresh start or resume alike) --
# it's shared across every shard process regardless of game directory,
# so it never resets on its own, and otherwise mixes errors from
# whatever code was running last time in with this run's. Doesn't touch
# results/status/etc -- those are what makes a resume a resume; archive
# those explicitly (archive_run.ps1 -IncludeResults) only when starting
# genuinely fresh.
#
# -Formats takes a comma-separated sequence (e.g. "singles,doubles"). With
# only one format and -ChunksPerShard 1 (both defaults), this is a plain
# static launch: each shard directory gets one persistent watchdog process
# (run_tournament.ps1) that runs every format in the list to completion,
# in order, in that same directory -- see run_tournament.ps1's own -Formats.
# Never launch more than one such watchdog against the same shard
# directory at once (see that script's header on why).
#
# Whenever there's more than one format, or -ChunksPerShard > 1, dispatch
# goes through a flat, priority-ordered work queue instead -- see
# run_remote_parallel.ps1's header for the exact rationale (finish every
# chunk of one format before any chunk of the next, without leaving a fast
# shard directory idle while a slow one grinds through its own static
# share). A background supervisor (supervise_local_chunks.ps1) reassigns a
# freed-up shard directory to the next queued (format, chunk) item -- each
# dispatch is single-format, so there's no cross-format recompile inside
# one job (never required anyway -- curse-stripping is a runtime
# ELO_FORMAT check, not compile-time; see tournament.rb's UNCURSED_RUN).
#
# -ChunksPerFormat overrides -ChunksPerShard's chunk count for specific
# formats, e.g. "singles_uncursed=3,doubles_uncursed=1" -- see
# run_remote_parallel.ps1's header for why (an uncursed subset rerun can
# have an order of magnitude fewer pairs than its cursed counterpart, not
# worth the same chunk count).
#
# -SubsetTrainerLabels/-SubsetPairsPath/-SubsetTag/-TurnTimeout: see
# tournament.rb and run_tournament.ps1's own headers.
param(
    [string]$Formats = "singles",
    [int]$ShardCount = 8,
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$PollIntervalSeconds = 5,
    [switch]$UseDebugFlag,
    [int]$SampleGamesPerTrainer = 0,   # 0 = full round robin; >0 = sparse random sampling
    [int]$SampleSeed = 1,
    [int]$ChunksPerShard = 1,
    [string]$ChunksPerFormat = "",
    [string]$SubsetTrainerLabels = "",
    [string]$SubsetPairsPath = "",
    [string]$SubsetTag = "subset",
    [int]$TurnTimeout = 0
)

. (Join-Path $PSScriptRoot "_chunk_queue.ps1")
. (Join-Path $PSScriptRoot "_local_chunk_launch.ps1")

$RepoRoot       = Split-Path -Parent $PSScriptRoot
$ResultsDir     = Join-Path $RepoRoot "results\local"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null
$QueueStatePath = Join-Path $ResultsDir "local_chunk_queue.json"
$LogPath        = Join-Path $ResultsDir "local_chunk_supervisor.log"

$formatList   = Get-FormatList $Formats
$ArchiveLabel = if ($SubsetTrainerLabels -or $SubsetPairsPath) { "$($formatList[0])_${SubsetTag}" } else { $formatList[0] }

& (Join-Path $PSScriptRoot "archive_run.ps1") -Label $ArchiveLabel

if ($formatList.Count -le 1 -and $ChunksPerShard -le 1) {
    Write-Output "Launching watchdogs (formats: $Formats) on $ShardCount local shard(s), one static chunk each, no supervisor..."
    for ($i = 0; $i -lt $ShardCount; $i++) {
        Invoke-LocalChunkLaunch -GameDirIndex $i -ShardIndex $i -ShardCount $ShardCount -Formats $Formats `
            -TurnStallTimeoutSeconds $TurnStallTimeoutSeconds -BattleStallTimeoutSeconds $BattleStallTimeoutSeconds `
            -PollIntervalSeconds $PollIntervalSeconds -SampleGamesPerTrainer $SampleGamesPerTrainer -SampleSeed $SampleSeed `
            -SubsetTrainerLabels $SubsetTrainerLabels -SubsetPairsPath $SubsetPairsPath -SubsetTag $SubsetTag -TurnTimeout $TurnTimeout `
            -UseDebugFlag:$UseDebugFlag | Out-Null
        Write-Output "Launched shard $i watchdog"
    }
    Write-Output ""
    Write-Output "$ShardCount shard watchdog(s) launched. Use watch_parallel_tournament.ps1 for aggregate live status."
    return
}

$defaultChunkCount = $ShardCount * $ChunksPerShard
$built = New-ChunkQueue -FormatList $formatList -DefaultChunkCount $defaultChunkCount -ChunksPerFormatOverride $ChunksPerFormat
$chunkCountByFormat = $built.chunkCountByFormat
$queue = $built.queue

$chunkCountSummary = Get-ChunkCountSummary -FormatList $formatList -ChunkCountByFormat $chunkCountByFormat
Write-Output "Launching watchdogs across $ShardCount local shard directory(ies), $($queue.Count) total work item(s) (chunk counts: $chunkCountSummary; format-major queue: $($formatList -join ' -> '))..."

$shardStates = @()
for ($i = 0; $i -lt $ShardCount; $i++) {
    if ($queue.Count -eq 0) {
        Write-Output "[shard $i] no work left in queue -- staying idle."
        $shardStates += [PSCustomObject]@{ index = $i; pid = $null; currentFormat = $null; currentChunk = $null; done = $true }
        continue
    }
    $item = $queue[0]
    $queue.RemoveAt(0)
    Write-Output "[shard $i] launching $($item.format) chunk $($item.chunk)..."
    $proc = Invoke-LocalChunkLaunch -GameDirIndex $i -ShardIndex ([int]$item.chunk) -ShardCount $chunkCountByFormat[$item.format] -Formats $item.format `
        -TurnStallTimeoutSeconds $TurnStallTimeoutSeconds -BattleStallTimeoutSeconds $BattleStallTimeoutSeconds `
        -PollIntervalSeconds $PollIntervalSeconds -SampleGamesPerTrainer $SampleGamesPerTrainer -SampleSeed $SampleSeed `
        -SubsetTrainerLabels $SubsetTrainerLabels -SubsetPairsPath $SubsetPairsPath -SubsetTag $SubsetTag -TurnTimeout $TurnTimeout `
        -UseDebugFlag:$UseDebugFlag
    $shardStates += [PSCustomObject]@{ index = $i; pid = $proc.Id; currentFormat = $item.format; currentChunk = $item.chunk; done = $false }
}

Write-Output ""
Write-Output "$ShardCount shard watchdog(s) launched."

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
    useDebugFlag              = [bool]$UseDebugFlag
    pendingQueue              = $queue.ToArray()
    shards                    = $shardStates
    updatedAt                 = (Get-Date -Format o)
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Path $QueueStatePath

# Relaunch via this same session's own executable, same reasoning as
# run_remote_parallel.ps1's identical line (short-name "pwsh"/"powershell"
# resolution has been flaky in scripted contexts -- see
# [[feedback-cross-tool-environment-gotchas]]).
$currentExe = (Get-Process -Id $PID).Path
$supervisorScript = Join-Path $PSScriptRoot "supervise_local_chunks.ps1"
$argLine = "-NoProfile -File `"$supervisorScript`" -QueueStatePath `"$QueueStatePath`" -LogPath `"$LogPath`""
$proc = Start-Process -FilePath $currentExe -WindowStyle Hidden -ArgumentList $argLine -PassThru

Write-Output "Supervisor started in the background (PID $($proc.Id); $($queue.Count) item(s) still queued after the initial launch, $ShardCount shard directories)."
Write-Output "  Queue state: $QueueStatePath"
Write-Output "  Supervisor log: $LogPath"
