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
# one directory would race on.
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
param(
    [string]$Format = "singles",
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$PollIntervalSeconds = 5,
    [int]$BattleLimit = 0,   # 0 = unlimited (run until the whole tournament is done)
    [int]$ShardIndex = 0,
    [int]$ShardCount = 1,
    [switch]$UseDebugFlag,
    [int]$SampleGamesPerTrainer = 0,   # 0 = full round robin; >0 = sparse random sampling
    [int]$SampleSeed = 1
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"
$GameDir    = if ($ShardCount -gt 1) {
    Join-Path $RepoRoot "shards\shard$ShardIndex"
} else {
    Join-Path $RepoRoot "vendor\tectonic-content"
}
$Suffix = if ($ShardCount -gt 1) { "${Format}_shard$ShardIndex" } else { $Format }

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

Write-Output "$(Get-Date -Format o)  [$Suffix] watchdog stopping. Status:"
if (Test-Path $env:ELO_STATUS_PATH) { Get-Content $env:ELO_STATUS_PATH }
