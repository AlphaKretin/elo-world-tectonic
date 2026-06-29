# One-shot meta-watchdog: polls the singles tournament's per-shard status
# files until every shard reports finished:true, then (by default)
# recompiles -- picking up the trainer_pool.rb Attea ALLOW_RANDOM_MOVES
# quarantine and the PokeBattle_DebugSceneNoLogging boss-AI no-op fixes,
# both added mid-singles-run and deliberately left uncompiled so as not to
# disrupt the live shards -- and launches the doubles tournament with the
# same shard/timeout/sampling parameters singles is using.
#
# Meant to be launched once (see the Start-Process invocation this was
# written alongside) as a detached, hidden process and then left alone --
# it does not need this shell or an IDE window to stay open. It exits
# itself right after kicking off run_parallel.ps1 -Format doubles, since
# that script's own per-shard watchdogs are already self-sufficient from
# there (same as how this run's singles shards have been running unwatched
# all along).
param(
    [string]$SinglesFormat = "singles",
    [string]$DoublesFormat = "doubles",
    [int]$ShardCount = 8,
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$SampleGamesPerTrainer = 30,
    [int]$SampleSeed = 1,
    [int]$PollIntervalSeconds = 60,
    [switch]$SkipRecompile
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"

function Get-AllSinglesFinished {
    for ($i = 0; $i -lt $ShardCount; $i++) {
        $statusPath = Join-Path $ResultsDir "elo_status_${SinglesFormat}_shard$i.json"
        if (-not (Test-Path $statusPath)) { return $false }
        if ((Get-Content $statusPath -Raw) -notmatch '"finished":true') { return $false }
    }
    return $true
}

function Get-LiveProcessCount {
    $games = Get-Process -Name Game -ErrorAction SilentlyContinue
    $watchdogs = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like '*run_tournament.ps1*' }
    return @($games).Count + @($watchdogs).Count
}

Write-Output "$(Get-Date -Format o)  Watchdog started. Polling every ${PollIntervalSeconds}s for all $ShardCount '$SinglesFormat' shards to report finished:true."

while (-not (Get-AllSinglesFinished)) {
    Start-Sleep -Seconds $PollIntervalSeconds
}

Write-Output "$(Get-Date -Format o)  All $ShardCount '$SinglesFormat' shards report finished:true."

# Belt-and-suspenders: the per-shard watchdog only re-checks finished:true
# after its own Game.exe exits, but wait for the process list to actually
# hit zero before touching the shard directories -- a recompile's
# robocopy /MIR sync would race a still-exiting Game.exe otherwise.
$deadline = (Get-Date).AddMinutes(2)
while ((Get-LiveProcessCount) -gt 0 -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
}
$remaining = Get-LiveProcessCount
if ($remaining -gt 0) {
    Write-Output "$(Get-Date -Format o)  WARNING: $remaining singles process(es) still alive after a 2min grace period -- proceeding anyway, but check for a stuck shard."
} else {
    Write-Output "$(Get-Date -Format o)  Confirmed 0 Game.exe / 0 run_tournament.ps1 processes remaining."
}

if (-not $SkipRecompile) {
    Write-Output "$(Get-Date -Format o)  Recompiling (setup_shards.ps1 -Recompile -ShardCount $ShardCount)..."
    & (Join-Path $PSScriptRoot "setup_shards.ps1") -ShardCount $ShardCount -Recompile
    Write-Output "$(Get-Date -Format o)  Recompile step done."
} else {
    Write-Output "$(Get-Date -Format o)  Skipping recompile (-SkipRecompile)."
}

Write-Output "$(Get-Date -Format o)  Launching doubles tournament (run_parallel.ps1 -Format $DoublesFormat -ShardCount $ShardCount -SampleGamesPerTrainer $SampleGamesPerTrainer -SampleSeed $SampleSeed)..."
& (Join-Path $PSScriptRoot "run_parallel.ps1") `
    -Format $DoublesFormat -ShardCount $ShardCount `
    -TurnStallTimeoutSeconds $TurnStallTimeoutSeconds -BattleStallTimeoutSeconds $BattleStallTimeoutSeconds `
    -SampleGamesPerTrainer $SampleGamesPerTrainer -SampleSeed $SampleSeed

Write-Output "$(Get-Date -Format o)  Doubles tournament launched. Meta-watchdog exiting."
