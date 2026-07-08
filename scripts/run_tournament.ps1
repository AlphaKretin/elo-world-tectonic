# Watchdog wrapper for the headless tournament.
#
# Game.exe is launched and re-launched in a loop until the tournament
# reports finished:true. Two failure modes were found that the in-process
# orchestration (tournament.rb) can't fully self-heal:
#   - The process can crash outright (e.g. a SystemStackError) -- handled by
#     just relaunching; tournament.rb's identity-based resume + crash-streak
#     tracking picks up where it left off.
#   - A specific turn can hang in a genuine infinite loop (still burning
#     CPU, never raising, never finishing) -- the engine itself never gives
#     up on this, so this script watches for it externally.
#
# Two independent timers, not one, because conflating them caused real
# (if slow) battles to get killed and discarded as false positives: a
# 100-round battle between two heavy-sustain teams that can't finish each
# other off is a legitimate ~140s+ battle, not a hang, since
# pbStartOfRoundPhase (see headless_boot.rb) keeps emitting a heartbeat
# every round. A single round that's actually stuck never updates that
# heartbeat at all.
#   - TurnStallTimeoutSeconds: resets whenever ELO_TURN_HEARTBEAT_PATH's
#     round number changes. Catches a genuinely stuck turn quickly. 30s
#     looked safe in isolation (a normal round resolves in low single-digit
#     seconds even for unusual interactions like PARADOXHERB+MIRRORHERB --
#     confirmed by running the exact pairing/seed that kept stalling here
#     standalone, which then completed cleanly every time), but pairings
#     that never hang alone still occasionally hit this threshold under
#     real 8-shard contention; bumped to 60s rather than chasing a bug that
#     may not exist in the battle logic at all.
#   - BattleStallTimeoutSeconds: resets whenever ELO_ATTEMPTING_PATH changes
#     (i.e. a new battle started). Backstop in case something progresses
#     turn-by-turn but the battle as a whole never ends.
#
# Pass -ShardIndex/-ShardCount to run this as one of several parallel
# shards (see run_parallel.ps1) -- each shard needs its own copy of the
# game directory (run setup_shards.ps1 first) since every debug launch
# recompiles Data/PluginScripts.rxdata, which concurrent instances sharing
# one directory would race on. This also means exactly one instance of
# THIS script may ever target a given shard directory at a time -- running
# two formats concurrently against the same shard dir races on the same
# Data/PluginScripts.rxdata and Saves/ files. -Formats (see below) is the
# supported way to run multiple formats against one shard directory; never
# launch two separate invocations of this script pointed at the same
# -ShardIndex/game directory.
#
# Launches without the "debug" argument by default: $DEBUG=true launches
# intermittently corrupt stdout/stderr ("Bad file descriptor", seemingly
# from console allocation racing with PowerShell's pipe redirection),
# confirmed absent across every non-debug run tried. logonerr (the per-
# move error path our had_error detection depends on) isn't gated by
# $DEBUG, so this doesn't lose error detection -- it only means
# pbCriticalCode's top-level rescue isn't active, which only mattered for
# logging a SystemStackError's already-empty backtrace before the process
# died anyway; the watchdog's dangling-crash detection doesn't depend on
# that log entry existing. Pass -UseDebugFlag after editing Plugin code,
# since only a debug launch recompiles Data/PluginScripts.rxdata.
#
# -Formats takes a comma-separated sequence (e.g. "singles,doubles"),
# mirroring remote_run_tournament.sh's --formats exactly: each format runs
# to completion (its own watchdog loop, own result/status/etc files) before
# the next one starts, all within this one process/shard directory. No
# recompile between formats -- curse-stripping is a runtime ELO_FORMAT
# check, not compile-time (see tournament.rb's UNCURSED_RUN), so nothing a
# format switch needs picked up by a fresh compile.
#
# -SubsetTrainerLabels (comma-separated, e.g. "TYPE:Name#Version,...")
# restricts this run to only pairings touching at least one given trainer
# label -- e.g. rerunning just the pairings affected by a specific
# trainer/behavior fix across the whole pool, without re-fighting
# everything. ELO_FORMAT stays the real format (so battle mode/curse
# stripping/etc all behave normally) but the results/status/etc files get
# an extra "_$SubsetTag" suffix (default "subset") so this partial result
# set never collides with the format's own full-round-robin file -- see
# analysis/apply_subset_rerun.py, which splices the results back in after.
#
# -SubsetPairsPath points at a tab-separated manifest (trainer1_label,
# trainer2_label per line, # comments/blank lines OK) restricting this run
# to exactly those pairings -- unlike -SubsetTrainerLabels, this doesn't
# pull in a trainer's *other* pairings too, so it's the right tool for
# rerunning e.g. just the handful of battles that hit the turn timeout.
# See tournament.rb's SUBSET_PAIRS_PATH. Composable with -SubsetTag the
# same way -SubsetTrainerLabels is. Accepts either one plain path (used for
# every format in -Formats) or a "format=path,format=path" list (via the
# same ConvertFrom-FormatKeyedOverrides parser _chunk_queue.ps1 uses for
# -ChunksPerFormat) when different formats' timed-out pairings live in
# different manifests -- e.g. "singles=Analysis/subset_pairs_singles.tsv,doubles=Analysis/subset_pairs_doubles.tsv".
# A format missing from the map gets no subset restriction at all (full
# round robin for that format) -- there's no separate "default" slot the
# way -ChunksPerFormat has, since an unrestricted format is a completely
# different (much bigger) kind of run, not a smaller variant of the same one.
#
# -TurnTimeout overrides the round count at which an autoTesting battle
# gets aborted as undecided (default 100, see Battle_StartAndEnd.rb's
# AUTO_TESTING_TURN_TIMEOUT) -- e.g. rerunning known-aborted battles with a
# longer cap to see if they resolve naturally instead. Raise
# -BattleStallTimeoutSeconds accordingly (a battle that legitimately runs
# to a longer cap takes proportionally longer, not just the ~140s a 100-
# round battle does) or the watchdog will kill it as a false-positive stall.
# -GameDirIndex picks which shards\shardN directory this process's Game.exe
# actually runs in -- independent of -ShardIndex/-ShardCount (the
# ELO_SHARD_INDEX/ELO_SHARD_COUNT pairing-pool split passed to
# tournament.rb). Defaults to -ShardIndex (so plain 1-chunk-per-shard usage,
# e.g. run_parallel.ps1's static path, needs nothing extra), but a chunk
# count finer than the physical shard count (see run_parallel.ps1's
# -ChunksPerShard) needs to freely reassign a freed-up directory to any
# chunk, not just the one matching its own directory number.
param(
    [string]$Formats = "singles",
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$PollIntervalSeconds = 5,
    [int]$BattleLimit = 0,   # 0 = unlimited (run until the whole tournament is done)
    [int]$ShardIndex = 0,
    [int]$ShardCount = 1,
    [int]$GameDirIndex = -1,   # -1 = use ShardIndex
    [switch]$UseDebugFlag,
    [int]$SampleGamesPerTrainer = 0,   # 0 = full round robin; >0 = sparse random sampling
    [int]$SampleSeed = 1,
    [string]$SubsetTrainerLabels = "",
    [string]$SubsetPairsPath = "",
    [string]$SubsetTag = "subset",
    [int]$TurnTimeout = 0   # 0 = keep the engine's own default (100)
)

$RepoRoot            = Split-Path -Parent $PSScriptRoot
$ResultsDir          = Join-Path $RepoRoot "results\local"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null
$EffectiveGameDirIndex = if ($GameDirIndex -ge 0) { $GameDirIndex } else { $ShardIndex }
# $ShardCount alone used to decide this (>1 => a shard directory, else the
# plain vendor/tectonic-content checkout) -- wrong once chunking exists:
# $ShardCount here is the pairing-pool split *for one format's chunk*, which
# a format with only 1 chunk (e.g. a tiny subset rerun's -ChunksPerFormat
# override) legitimately sets to 1 even though this is very much still a
# physically-sharded local dispatch. -GameDirIndex being explicitly passed
# (>= 0) is _local_chunk_launch.ps1's actual signal for "this is one of
# several parallel shard directories" -- confirmed live 2026-07-08: a
# doubles_uncursed chunk (ShardCount=1 for that format) launched straight
# into vendor\tectonic-content instead of its assigned shards\shardN,
# racing every other format/chunk that happened to land on shard0 that run.
$UsingShardDirectory = ($GameDirIndex -ge 0) -or ($ShardCount -gt 1)
$GameDir    = if ($UsingShardDirectory) {
    Join-Path $RepoRoot "shards\shard$EffectiveGameDirIndex"
} else {
    Join-Path $RepoRoot "vendor\tectonic-content"
}

# See this script's own -SubsetPairsPath header comment: a bare path (no
# "=") applies to every format in -Formats unchanged (the original,
# single-manifest behavior); a "format=path,..." map (parsed via
# _chunk_queue.ps1's ConvertFrom-FormatKeyedOverrides, dot-sourced below)
# resolves per format, with a format missing from the map getting no subset
# restriction at all. Passes no format list to validate against -- unlike
# -ChunksPerFormat (validated once, up front, against the whole -Formats
# sequence at the run_parallel.ps1/run_remote_parallel.ps1 layer), a chunked
# dispatch hands this *one* process only its own single assigned format via
# -Formats, so this map can legitimately reference formats this particular
# process's own $FormatList has never heard of.
function Resolve-SubsetPairsPathForFormat([string]$Format) {
    if (-not $SubsetPairsPath) { return "" }
    if ($SubsetPairsPath -notmatch "=") { return $SubsetPairsPath }
    $map = ConvertFrom-FormatKeyedOverrides -Raw $SubsetPairsPath -FormatList @() -FieldName "subset-pairs-path"
    if ($map.ContainsKey($Format)) { return $map[$Format] }
    return ""
}

# Runs exactly one format to completion against $GameDir/$ShardIndex, i.e.
# the entire body that used to be this whole script back when it only
# took a single -Format. Factored out so -Formats can loop over it the same
# way remote_run_tournament.sh's run_format() does.
function Invoke-TournamentFormat([string]$Format) {
    $EffectiveSubsetPairsPath = Resolve-SubsetPairsPathForFormat $Format
    $FormatTag = if ($SubsetTrainerLabels -or $EffectiveSubsetPairsPath) { "${Format}_${SubsetTag}" } else { $Format }
    # Same $UsingShardDirectory signal as $GameDir above, not a second
    # $ShardCount -gt 1 check -- a single-chunk format (-ChunksPerFormat
    # foo=1) still needs its own "_shard<N>" suffix despite ShardCount being
    # 1 for that format, both to stay collision-safe with any other chunk
    # dispatched into the same physical directory over this run's lifetime,
    # and because watch_parallel_tournament.ps1's aggregate view only globs
    # "*_shard*.json" -- a suffix-less file from this branch would silently
    # never show up there.
    $Suffix = if ($UsingShardDirectory) { "${FormatTag}_shard$ShardIndex" } else { $FormatTag }

    $env:ELO_TOURNAMENT          = "1"
    $env:ELO_FORMAT              = $Format
    $env:ELO_SHARD_INDEX         = "$ShardIndex"
    $env:ELO_SHARD_COUNT         = "$ShardCount"
    $env:ELO_RESULTS_PATH        = Join-Path $ResultsDir "elo_results_$Suffix.jsonl"
    $env:ELO_STATUS_PATH         = Join-Path $ResultsDir "elo_status_$Suffix.json"
    $env:ELO_ATTEMPTING_PATH     = Join-Path $ResultsDir "elo_attempting_$Suffix.json"
    $env:ELO_CRASH_STREAK_PATH   = Join-Path $ResultsDir "elo_crash_streaks_$Suffix.txt"
    $env:ELO_TURN_HEARTBEAT_PATH = Join-Path $ResultsDir "elo_turn_heartbeat_$Suffix.json"
    if ($BattleLimit -gt 0) {
        $env:ELO_BATTLE_LIMIT = "$BattleLimit"
    } else {
        Remove-Item Env:\ELO_BATTLE_LIMIT -ErrorAction SilentlyContinue
    }
    if ($SampleGamesPerTrainer -gt 0) {
        $env:ELO_SAMPLE_GAMES_PER_TRAINER = "$SampleGamesPerTrainer"
        $env:ELO_SAMPLE_SEED = "$SampleSeed"
    } else {
        Remove-Item Env:\ELO_SAMPLE_GAMES_PER_TRAINER -ErrorAction SilentlyContinue
    }
    if ($SubsetTrainerLabels) {
        $env:ELO_SUBSET_TRAINER_LABELS = $SubsetTrainerLabels
    } else {
        Remove-Item Env:\ELO_SUBSET_TRAINER_LABELS -ErrorAction SilentlyContinue
    }
    if ($EffectiveSubsetPairsPath) {
        $env:ELO_SUBSET_PAIRS_PATH = $EffectiveSubsetPairsPath
    } else {
        Remove-Item Env:\ELO_SUBSET_PAIRS_PATH -ErrorAction SilentlyContinue
    }
    if ($TurnTimeout -gt 0) {
        $env:ELO_TURN_TIMEOUT = "$TurnTimeout"
    } else {
        Remove-Item Env:\ELO_TURN_TIMEOUT -ErrorAction SilentlyContinue
    }

    function Get-Finished {
        if (-not (Test-Path $env:ELO_STATUS_PATH)) { return $false }
        return (Get-Content $env:ELO_STATUS_PATH -Raw) -match '"finished":true'
    }

    while (-not (Get-Finished)) {
        Push-Location $GameDir
        if ($UseDebugFlag) {
            $proc = Start-Process -FilePath ".\Game.exe" -ArgumentList "debug" -PassThru `
                -RedirectStandardOutput (Join-Path $ResultsDir "game_stdout_$Suffix.log") `
                -RedirectStandardError  (Join-Path $ResultsDir "game_stderr_$Suffix.log")
        } else {
            $proc = Start-Process -FilePath ".\Game.exe" -PassThru `
                -RedirectStandardOutput (Join-Path $ResultsDir "game_stdout_$Suffix.log") `
                -RedirectStandardError  (Join-Path $ResultsDir "game_stderr_$Suffix.log")
        }
        Pop-Location

        Write-Output "$(Get-Date -Format o)  [$Suffix] launched Game.exe (PID $($proc.Id))"

        $lastBattleProgressAt   = Get-Date
        $lastAttemptingSnapshot = $null
        $lastTurnProgressAt     = Get-Date
        $lastHeartbeatSnapshot  = $null

        while (-not $proc.HasExited) {
            Start-Sleep -Seconds $PollIntervalSeconds

            if (Test-Path $env:ELO_ATTEMPTING_PATH) {
                $current = Get-Content $env:ELO_ATTEMPTING_PATH -Raw
                if ($current -ne $lastAttemptingSnapshot) {
                    $lastAttemptingSnapshot = $current
                    $lastBattleProgressAt   = Get-Date
                    # New battle => round count resets too.
                    $lastTurnProgressAt    = Get-Date
                    $lastHeartbeatSnapshot = $null
                }
            }

            if (Test-Path $env:ELO_TURN_HEARTBEAT_PATH) {
                $currentHeartbeat = Get-Content $env:ELO_TURN_HEARTBEAT_PATH -Raw
                if ($currentHeartbeat -ne $lastHeartbeatSnapshot) {
                    $lastHeartbeatSnapshot = $currentHeartbeat
                    $lastTurnProgressAt    = Get-Date
                }
            }

            $turnStalledSeconds   = ((Get-Date) - $lastTurnProgressAt).TotalSeconds
            $battleStalledSeconds = ((Get-Date) - $lastBattleProgressAt).TotalSeconds

            if ($turnStalledSeconds -gt $TurnStallTimeoutSeconds) {
                Write-Output "$(Get-Date -Format o)  [$Suffix] turn stalled ${turnStalledSeconds}s (heartbeat: $lastHeartbeatSnapshot) on: $lastAttemptingSnapshot -- killing PID $($proc.Id)"
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                break
            }
            if ($battleStalledSeconds -gt $BattleStallTimeoutSeconds) {
                Write-Output "$(Get-Date -Format o)  [$Suffix] battle stalled ${battleStalledSeconds}s on: $lastAttemptingSnapshot -- killing PID $($proc.Id)"
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                break
            }
        }

        if ($proc.HasExited) {
            Write-Output "$(Get-Date -Format o)  [$Suffix] Game.exe exited (code $($proc.ExitCode))"
        }

        if ($BattleLimit -gt 0) {
            Write-Output "[$Suffix] Battle limit reached for this invocation; not auto-relaunching."
            break
        }

        Start-Sleep -Seconds 2
    }

    Write-Output "$(Get-Date -Format o)  [$Suffix] watchdog stopping for format '$Format'. Status:"
    if (Test-Path $env:ELO_STATUS_PATH) { Get-Content $env:ELO_STATUS_PATH }
}

. (Join-Path $PSScriptRoot "_chunk_queue.ps1")

$FormatList = Get-FormatList $Formats
for ($i = 0; $i -lt $FormatList.Count; $i++) {
    $fmt = $FormatList[$i]
    Write-Output "$(Get-Date -Format o)  [shard$ShardIndex] starting format '$fmt' ($i/$($FormatList.Count))"
    Invoke-TournamentFormat -Format $fmt
}

Write-Output "$(Get-Date -Format o)  [shard$ShardIndex] all formats finished. Watchdog exiting."
