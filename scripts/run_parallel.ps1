# Launches ShardCount parallel tournament watchdogs (run_tournament.ps1),
# each in its own PowerShell process against its own shard game directory
# (run setup_shards.ps1 first). Each shard's output streams to its own log
# under results/; this script just launches them and returns -- use
# watch_tournament_parallel.ps1 to see aggregate live progress.
param(
    [string]$Format = "singles",
    [int]$ShardCount = 8,
    [int]$StallTimeoutSeconds = 90,
    [int]$PollIntervalSeconds = 5
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"
$ScriptPath = Join-Path $PSScriptRoot "run_tournament.ps1"

for ($i = 0; $i -lt $ShardCount; $i++) {
    $logPath = Join-Path $ResultsDir "watchdog_${Format}_shard$i.log"
    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$ScriptPath`"",
        "-Format", $Format,
        "-ShardIndex", $i,
        "-ShardCount", $ShardCount,
        "-StallTimeoutSeconds", $StallTimeoutSeconds,
        "-PollIntervalSeconds", $PollIntervalSeconds
    )
    Start-Process -FilePath "powershell.exe" -ArgumentList $argList `
        -RedirectStandardOutput $logPath -RedirectStandardError $logPath `
        -WindowStyle Hidden
    Write-Output "Launched shard $i watchdog (log: $logPath)"
}

Write-Output ""
Write-Output "$ShardCount shard watchdogs launched. Use watch_tournament_parallel.ps1 for aggregate live status."
