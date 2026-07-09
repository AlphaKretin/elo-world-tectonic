# Runs exactly one explicit pairing (not a pool scan) -- the scripted
# wrapper for EloTournament.testSinglePairing! (see tournament.rb). Meant
# for ad hoc diagnosis of a specific matchup/seed, e.g. reproducing a
# reported crash or checking whether a behavior fix changed one battle's
# outcome, without paying for a full tournament run.
#
# -T1PartyIndices/-T2PartyIndices (comma-separated, 0-based) trims that
# trainer's party down to just the given Pokemon before the battle --
# useful for bisecting which party member is responsible for a crash/hang.
#
# -PrebattleOnly stops before the battle starts and just records each
# side's (seeded) party species -- handy for confirming a seed produces
# the roll you expect before spending time on the battle itself.
#
# -BattleMode is the engine's own "single"/"double"/"triple" literal (see
# AIBenchmark.runBattle's battleMode:), not this repo's "singles"/"doubles"
# ELO_FORMAT convention used elsewhere -- testSinglePairing! passes
# ELO_TEST_FORMAT straight through unconverted.
#
# Runs directly in vendor/tectonic-content (no shard dir) -- it's one
# battle, so there's no pool to parallelize across. ELO_TEST_RESULTS_PATH
# (shared with run_custom_trainer.ps1/run_batch_pairings.ps1) points the
# engine straight at results\local\ instead of the game dir's own
# Analysis\, so there's no shard-local file for a future
# setup_shards.ps1 -Recompile to wipe -- see run_custom_trainer.ps1's
# header comment for the incident that motivated that convention.
param(
    [Parameter(Mandatory)][string]$T1Type,
    [Parameter(Mandatory)][string]$T1Name,
    [int]$T1Version = 0,
    [string]$T1PartyIndices = "",

    [Parameter(Mandatory)][string]$T2Type,
    [Parameter(Mandatory)][string]$T2Name,
    [int]$T2Version = 0,
    [string]$T2PartyIndices = "",

    [int]$Seed = 1,
    [string]$BattleMode = "single",
    [switch]$PrebattleOnly
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results\local"
$GameDir    = Join-Path $RepoRoot "vendor\tectonic-content"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

$stamp      = Get-Date -Format "yyyyMMdd_HHmmss"
$destResult = Join-Path $ResultsDir "single_pairing_test_$stamp.txt"

$env:ELO_TOURNAMENT          = "1"
$env:ELO_TEST_SINGLE_PAIRING = "1"
$env:ELO_TEST_RESULTS_PATH   = $destResult
$env:ELO_TEST_T1_TYPE        = $T1Type
$env:ELO_TEST_T1_NAME        = $T1Name
$env:ELO_TEST_T1_VERSION     = "$T1Version"
$env:ELO_TEST_T2_TYPE        = $T2Type
$env:ELO_TEST_T2_NAME        = $T2Name
$env:ELO_TEST_T2_VERSION     = "$T2Version"
$env:ELO_TEST_SEED           = "$Seed"
$env:ELO_TEST_FORMAT         = $BattleMode
if ($T1PartyIndices) { $env:ELO_TEST_T1_PARTY_INDICES = $T1PartyIndices } else { Remove-Item Env:\ELO_TEST_T1_PARTY_INDICES -ErrorAction SilentlyContinue }
if ($T2PartyIndices) { $env:ELO_TEST_T2_PARTY_INDICES = $T2PartyIndices } else { Remove-Item Env:\ELO_TEST_T2_PARTY_INDICES -ErrorAction SilentlyContinue }
if ($PrebattleOnly) { $env:ELO_TEST_PREBATTLE_ONLY = "1" } else { Remove-Item Env:\ELO_TEST_PREBATTLE_ONLY -ErrorAction SilentlyContinue }

Push-Location $GameDir
$proc = Start-Process -FilePath ".\Game.exe" -PassThru -Wait `
    -RedirectStandardOutput (Join-Path $ResultsDir "single_pairing_stdout.log") `
    -RedirectStandardError  (Join-Path $ResultsDir "single_pairing_stderr.log")
Pop-Location

Remove-Item Env:\ELO_TOURNAMENT, Env:\ELO_TEST_SINGLE_PAIRING, Env:\ELO_TEST_RESULTS_PATH, Env:\ELO_TEST_T1_TYPE, `
    Env:\ELO_TEST_T1_NAME, Env:\ELO_TEST_T1_VERSION, Env:\ELO_TEST_T2_TYPE, Env:\ELO_TEST_T2_NAME, Env:\ELO_TEST_T2_VERSION, `
    Env:\ELO_TEST_SEED, Env:\ELO_TEST_FORMAT, Env:\ELO_TEST_T1_PARTY_INDICES, Env:\ELO_TEST_T2_PARTY_INDICES, `
    Env:\ELO_TEST_PREBATTLE_ONLY -ErrorAction SilentlyContinue

if (-not (Test-Path $destResult)) {
    Write-Output "Game.exe exited (code $($proc.ExitCode)) but produced no result file -- check single_pairing_stderr.log."
    exit 1
}

Write-Output "Result (saved to $destResult):"
Get-Content $destResult
