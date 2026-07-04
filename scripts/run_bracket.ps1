# Watchdog wrapper for the headless top-16 elimination bracket (bracket.rb).
#
# Mirrors run_tournament.ps1's stall-detection design -- same turn-heartbeat /
# attempting-file mechanism, generic in tournament.rb/headless_boot.rb -- but
# launches the whole bracket (15 matches) as a single, unsharded process.
# There's no need to parallelize 15 battles across shards the way the full
# round robin needs to.
#
# Prereq: analysis/bracket_seeds.py must have already written
# results/bracket_seeds_<format>.txt (top 16 from ratings_<format>.json).
#
# Pass -UseDebugFlag the first run after adding/editing bracket.rb, since
# only a debug launch recompiles Data/PluginScripts.rxdata.
param(
    [string]$Format = "singles",
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$PollIntervalSeconds = 5,
    [switch]$UseDebugFlag
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"
$GameDir = Join-Path $RepoRoot "vendor\tectonic-content"
$SeedsPath = Join-Path $ResultsDir "bracket_seeds_$Format.txt"

if (-not (Test-Path $SeedsPath)) {
    Write-Error "Seeds file not found: $SeedsPath -- run '.\.venv\Scripts\python.exe analysis\bracket_seeds.py --format $Format' first."
    exit 1
}

$env:ELO_TOURNAMENT = "1"
$env:ELO_RUN_BRACKET = "1"
$env:ELO_FORMAT = $Format   # labels the attempting-file snapshot AND tells bracket.rb whether to curse-strip entrants (UNCURSED_BRACKET)
$env:ELO_BRACKET_FORMAT = if ($Format -like "double*") { "double" } else { "single" }
$env:ELO_BRACKET_SEEDS_PATH = $SeedsPath
$env:ELO_BRACKET_RESULTS_PATH = Join-Path $ResultsDir "bracket_${Format}_results.tsv"
$env:ELO_BRACKET_STATUS_PATH = Join-Path $ResultsDir "bracket_${Format}_status.json"
$env:ELO_ATTEMPTING_PATH = Join-Path $ResultsDir "bracket_${Format}_attempting.json"
$env:ELO_TURN_HEARTBEAT_PATH = Join-Path $ResultsDir "bracket_${Format}_turn_heartbeat.json"

function Get-Finished {
    if (-not (Test-Path $env:ELO_BRACKET_STATUS_PATH)) { return $false }
    return (Get-Content $env:ELO_BRACKET_STATUS_PATH -Raw) -match '"finished":true'
}

while (-not (Get-Finished)) {
    Push-Location $GameDir
    if ($UseDebugFlag) {
        $proc = Start-Process -FilePath ".\Game.exe" -ArgumentList "debug" -PassThru `
            -RedirectStandardOutput (Join-Path $ResultsDir "bracket_${Format}_stdout.log") `
            -RedirectStandardError  (Join-Path $ResultsDir "bracket_${Format}_stderr.log")
    }
    else {
        $proc = Start-Process -FilePath ".\Game.exe" -PassThru `
            -RedirectStandardOutput (Join-Path $ResultsDir "bracket_${Format}_stdout.log") `
            -RedirectStandardError  (Join-Path $ResultsDir "bracket_${Format}_stderr.log")
    }
    Pop-Location

    Write-Output "$(Get-Date -Format o)  [bracket-$Format] launched Game.exe (PID $($proc.Id))"

    $lastBattleProgressAt = Get-Date
    $lastAttemptingSnapshot = $null
    $lastTurnProgressAt = Get-Date
    $lastHeartbeatSnapshot = $null

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds $PollIntervalSeconds

        if (Test-Path $env:ELO_ATTEMPTING_PATH) {
            $current = Get-Content $env:ELO_ATTEMPTING_PATH -Raw
            if ($current -ne $lastAttemptingSnapshot) {
                $lastAttemptingSnapshot = $current
                $lastBattleProgressAt = Get-Date
                # New battle => round count resets too.
                $lastTurnProgressAt = Get-Date
                $lastHeartbeatSnapshot = $null
            }
        }

        if (Test-Path $env:ELO_TURN_HEARTBEAT_PATH) {
            $currentHeartbeat = Get-Content $env:ELO_TURN_HEARTBEAT_PATH -Raw
            if ($currentHeartbeat -ne $lastHeartbeatSnapshot) {
                $lastHeartbeatSnapshot = $currentHeartbeat
                $lastTurnProgressAt = Get-Date
            }
        }

        $turnStalledSeconds = ((Get-Date) - $lastTurnProgressAt).TotalSeconds
        $battleStalledSeconds = ((Get-Date) - $lastBattleProgressAt).TotalSeconds

        if ($turnStalledSeconds -gt $TurnStallTimeoutSeconds) {
            Write-Output "$(Get-Date -Format o)  [bracket-$Format] turn stalled ${turnStalledSeconds}s (heartbeat: $lastHeartbeatSnapshot) on: $lastAttemptingSnapshot -- killing PID $($proc.Id)"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            break
        }
        if ($battleStalledSeconds -gt $BattleStallTimeoutSeconds) {
            Write-Output "$(Get-Date -Format o)  [bracket-$Format] battle stalled ${battleStalledSeconds}s on: $lastAttemptingSnapshot -- killing PID $($proc.Id)"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            break
        }
    }

    if ($proc.HasExited) {
        Write-Output "$(Get-Date -Format o)  [bracket-$Format] Game.exe exited (code $($proc.ExitCode))"
    }

    Start-Sleep -Seconds 2
}

Write-Output "$(Get-Date -Format o)  [bracket-$Format] bracket finished. Status:"
Get-Content $env:ELO_BRACKET_STATUS_PATH
