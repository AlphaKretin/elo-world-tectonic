# Shared by run_parallel.ps1 and supervise_local_chunks.ps1, dot-sourced by
# both, mirroring _remote_chunk_launch.ps1's role but for local shard
# directories instead of remote droplets -- a chunk dispatch is
# always identical regardless of whether it's this run's very first launch
# or a mid-run reassignment after some other chunk finished first.
#
# A physical shard directory (setup_shards.ps1's shards\shardN) and the
# (format, chunk) pairing-slice currently running in it are independent:
# -GameDirIndex picks the directory (i.e. which Game.exe process this is),
# while -ShardIndex/-ShardCount are the ELO_SHARD_INDEX/ELO_SHARD_COUNT
# pairing-pool split passed through to tournament.rb. This split is what
# lets a chunk count finer than the physical shard count freely reassign a
# freed-up directory to whichever chunk is next in the queue, not just the
# one matching its own directory number -- see run_tournament.ps1's
# -GameDirIndex.
function Invoke-LocalChunkLaunch {
    param(
        [Parameter(Mandatory)][int]$GameDirIndex,
        [Parameter(Mandatory)][int]$ShardIndex,
        [Parameter(Mandatory)][int]$ShardCount,
        [Parameter(Mandatory)][string]$Formats,
        [int]$TurnStallTimeoutSeconds = 60,
        [int]$BattleStallTimeoutSeconds = 240,
        [int]$PollIntervalSeconds = 5,
        [int]$SampleGamesPerTrainer = 0,
        [int]$SampleSeed = 1,
        [string]$SubsetTrainerLabels = "",
        [string]$SubsetPairsPath = "",
        [string]$SubsetTag = "subset",
        [int]$TurnTimeout = 0,
        [switch]$UseDebugFlag
    )

    $ScriptPath = Join-Path $PSScriptRoot "run_tournament.ps1"
    $RepoRoot   = Split-Path -Parent $PSScriptRoot
    $ResultsDir = Join-Path $RepoRoot "results"
    # Directory + chunk both in the log name -- a directory's Nth chunk
    # across a run's lifetime would otherwise all share one log file name,
    # silently truncating/overwriting each other's watchdog output.
    $logTag = "gamedir${GameDirIndex}_$($Formats)_chunk${ShardIndex}"

    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$ScriptPath`"",
        "-Formats", $Formats,
        "-GameDirIndex", $GameDirIndex,
        "-ShardIndex", $ShardIndex,
        "-ShardCount", $ShardCount,
        "-TurnStallTimeoutSeconds", $TurnStallTimeoutSeconds,
        "-BattleStallTimeoutSeconds", $BattleStallTimeoutSeconds,
        "-PollIntervalSeconds", $PollIntervalSeconds
    )
    if ($UseDebugFlag) { $argList += "-UseDebugFlag" }
    if ($SampleGamesPerTrainer -gt 0) {
        $argList += @("-SampleGamesPerTrainer", $SampleGamesPerTrainer, "-SampleSeed", $SampleSeed)
    }
    if ($SubsetTrainerLabels) {
        $argList += @("-SubsetTrainerLabels", "`"$SubsetTrainerLabels`"", "-SubsetTag", $SubsetTag)
    }
    if ($SubsetPairsPath) {
        $argList += @("-SubsetPairsPath", "`"$SubsetPairsPath`"", "-SubsetTag", $SubsetTag)
    }
    if ($TurnTimeout -gt 0) {
        $argList += @("-TurnTimeout", $TurnTimeout)
    }

    $outLogPath = Join-Path $ResultsDir "watchdog_${logTag}.log"
    $errLogPath = Join-Path $ResultsDir "watchdog_${logTag}_err.log"
    # Launch via the calling process's own exe path, not a bare "powershell.exe"
    # short name -- same reasoning as run_parallel.ps1/run_remote_parallel.ps1's
    # identical supervisor-relaunch line (see [[feedback-cross-tool-environment-gotchas]]):
    # short-name resolution has been flaky in scripted/non-interactive contexts,
    # and this call site hit that directly ("The system cannot find the file
    # specified.") since this session runs pwsh.exe, not a separately-resolvable
    # powershell.exe. Correct regardless of which process calls this function
    # (run_parallel.ps1 or supervise_local_chunks.ps1) since $PID is always
    # the actual calling process's own PID.
    $currentExe = (Get-Process -Id $PID).Path
    return Start-Process -FilePath $currentExe -ArgumentList $argList `
        -RedirectStandardOutput $outLogPath -RedirectStandardError $errLogPath `
        -WindowStyle Hidden -PassThru
}
