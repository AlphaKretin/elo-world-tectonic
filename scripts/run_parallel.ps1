# Launches ShardCount parallel tournament watchdogs (run_tournament.ps1),
# each in its own PowerShell process against its own shard game directory
# (run setup_shards.ps1 first). Each shard's output streams to its own log
# under results/; this script just launches them and returns -- use
# watch_tournament_parallel.ps1 to see aggregate live progress.
#
# Always archives errorlog.txt first (fresh start or resume alike) --
# it's shared across every shard process regardless of game directory,
# so it never resets on its own, and otherwise mixes errors from
# whatever code was running last time in with this run's. Doesn't touch
# results/status/etc -- those are what makes a resume a resume; archive
# those explicitly (archive_run.ps1 -IncludeResults) only when starting
# genuinely fresh.
param(
    [string]$Format = "singles",
    [int]$ShardCount = 8,
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$PollIntervalSeconds = 5,
    [switch]$UseDebugFlag,
    [int]$SampleGamesPerTrainer = 0,   # 0 = full round robin; >0 = sparse random sampling
    [int]$SampleSeed = 1
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"
$ScriptPath = Join-Path $PSScriptRoot "run_tournament.ps1"

& (Join-Path $PSScriptRoot "archive_run.ps1") -Label $Format

for ($i = 0; $i -lt $ShardCount; $i++) {
    $outLogPath = Join-Path $ResultsDir "watchdog_${Format}_shard$i.log"
    $errLogPath = Join-Path $ResultsDir "watchdog_${Format}_shard${i}_err.log"
    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$ScriptPath`"",
        "-Format", $Format,
        "-ShardIndex", $i,
        "-ShardCount", $ShardCount,
        "-TurnStallTimeoutSeconds", $TurnStallTimeoutSeconds,
        "-BattleStallTimeoutSeconds", $BattleStallTimeoutSeconds,
        "-PollIntervalSeconds", $PollIntervalSeconds
    )
    if ($UseDebugFlag) { $argList += "-UseDebugFlag" }
    if ($SampleGamesPerTrainer -gt 0) {
        $argList += @("-SampleGamesPerTrainer", $SampleGamesPerTrainer, "-SampleSeed", $SampleSeed)
    }
    Start-Process -FilePath "powershell.exe" -ArgumentList $argList `
        -RedirectStandardOutput $outLogPath -RedirectStandardError $errLogPath `
        -WindowStyle Hidden
    Write-Output "Launched shard $i watchdog (log: $outLogPath)"
}

Write-Output ""
Write-Output "$ShardCount shard watchdogs launched. Use watch_tournament_parallel.ps1 for aggregate live status."
