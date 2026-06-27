# Watchdog wrapper for the headless tournament.
#
# Game.exe is launched and re-launched in a loop until the tournament
# reports finished:true. Two failure modes were found that the in-process
# orchestration (tournament.rb) can't fully self-heal:
#   - The process can crash outright (e.g. a SystemStackError) -- handled by
#     just relaunching; tournament.rb's identity-based resume + crash-streak
#     tracking picks up where it left off.
#   - A specific matchup can hang in a genuine infinite loop (still burning
#     CPU, never raising, never finishing a turn) -- the engine itself never
#     gives up on this, so this script watches ELO_ATTEMPTING_PATH and kills
#     the process if it sits on the same pairing too long. The killed
#     process counts as "crashed mid-battle" to tournament.rb, so the same
#     crash-streak skip-after-N-failures logic applies to hangs too.
#
# Pass -ShardIndex/-ShardCount to run this as one of several parallel
# shards (see run_parallel.ps1) -- each shard needs its own copy of the
# game directory (run setup_shards.ps1 first) since every debug launch
# recompiles Data/PluginScripts.rxdata, which concurrent instances sharing
# one directory would race on.
param(
    [string]$Format = "singles",
    [int]$StallTimeoutSeconds = 90,
    [int]$PollIntervalSeconds = 5,
    [int]$BattleLimit = 0,   # 0 = unlimited (run until the whole tournament is done)
    [int]$ShardIndex = 0,
    [int]$ShardCount = 1
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"
$GameDir    = if ($ShardCount -gt 1) {
    Join-Path $RepoRoot "shards\shard$ShardIndex"
} else {
    Join-Path $RepoRoot "vendor\tectonic-content"
}
$Suffix = if ($ShardCount -gt 1) { "${Format}_shard$ShardIndex" } else { $Format }

$env:ELO_TOURNAMENT        = "1"
$env:ELO_FORMAT            = $Format
$env:ELO_SHARD_INDEX       = "$ShardIndex"
$env:ELO_SHARD_COUNT       = "$ShardCount"
$env:ELO_RESULTS_PATH      = Join-Path $ResultsDir "elo_results_$Suffix.jsonl"
$env:ELO_STATUS_PATH       = Join-Path $ResultsDir "elo_status_$Suffix.json"
$env:ELO_ATTEMPTING_PATH   = Join-Path $ResultsDir "elo_attempting_$Suffix.json"
$env:ELO_CRASH_STREAK_PATH = Join-Path $ResultsDir "elo_crash_streaks_$Suffix.txt"
if ($BattleLimit -gt 0) {
    $env:ELO_BATTLE_LIMIT = "$BattleLimit"
} else {
    Remove-Item Env:\ELO_BATTLE_LIMIT -ErrorAction SilentlyContinue
}

function Get-Finished {
    if (-not (Test-Path $env:ELO_STATUS_PATH)) { return $false }
    return (Get-Content $env:ELO_STATUS_PATH -Raw) -match '"finished":true'
}

while (-not (Get-Finished)) {
    Push-Location $GameDir
    $proc = Start-Process -FilePath ".\Game.exe" -ArgumentList "debug" -PassThru `
        -RedirectStandardOutput (Join-Path $ResultsDir "game_stdout_$Suffix.log") `
        -RedirectStandardError  (Join-Path $ResultsDir "game_stderr_$Suffix.log")
    Pop-Location

    Write-Output "$(Get-Date -Format o)  [$Suffix] launched Game.exe (PID $($proc.Id))"

    $lastProgressAt      = Get-Date
    $lastAttemptingSnapshot = $null

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds $PollIntervalSeconds

        if (Test-Path $env:ELO_ATTEMPTING_PATH) {
            $current = Get-Content $env:ELO_ATTEMPTING_PATH -Raw
            if ($current -ne $lastAttemptingSnapshot) {
                $lastAttemptingSnapshot = $current
                $lastProgressAt = Get-Date
            }
        }

        $stalledSeconds = ((Get-Date) - $lastProgressAt).TotalSeconds
        if ($stalledSeconds -gt $StallTimeoutSeconds) {
            Write-Output "$(Get-Date -Format o)  [$Suffix] stalled ${stalledSeconds}s on: $lastAttemptingSnapshot -- killing PID $($proc.Id)"
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
