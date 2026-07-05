# Re-runs one exact stored (trainer1, trainer2, format, seed) battle with
# recording enabled (EloTournament.saveReplay! / replay.rb), producing a
# .dat watchable in-game via the VS Recorder.
#
# -Trainer1/-Trainer2 take the same "TYPE:Name" / "TYPE:Name#version" label
# that trainerLabel() writes into results/elo_results_*.jsonl and
# results/bracket_seeds_*.txt (version suffix omitted when 0), so a row
# pulled straight out of either file can be pasted in as-is, e.g.:
#   .\scripts\save_replay.ps1 -Trainer1 "LEADER_Noel:Noel" -Trainer2 "LEADER_Noel:Noel#1" -Seed 1485444510
#
# Pass -UseDebugFlag after editing Plugin code, since only a debug launch
# recompiles Data/PluginScripts.rxdata.
param(
    [Parameter(Mandatory)][string]$Trainer1,
    [Parameter(Mandatory)][string]$Trainer2,
    [Parameter(Mandatory)][int64]$Seed,
    [string]$Format = "singles",
    [string]$OutputName,
    [switch]$UseDebugFlag
)

function Set-ReplayTrainerEnv {
    param(
        [Parameter(Mandatory)][string]$Prefix,
        [Parameter(Mandatory)][string]$Label
    )
    if ($Label -notmatch '^(?<type>[^:#]+):(?<name>[^#]+)(#(?<version>\d+))?$') {
        throw "Trainer label '$Label' isn't in TYPE:Name or TYPE:Name#version form (see trainerLabel in trainer_pool.rb)."
    }
    Set-Item "Env:ELO_REPLAY_${Prefix}_TYPE" $Matches.type
    Set-Item "Env:ELO_REPLAY_${Prefix}_NAME" $Matches.name
    Set-Item "Env:ELO_REPLAY_${Prefix}_VERSION" $(if ($Matches.version) { $Matches.version } else { "0" })
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"
$GameDir = Join-Path $RepoRoot "vendor\tectonic-content"

$env:ELO_TOURNAMENT = "1"
$env:ELO_SAVE_REPLAY = "1"
$env:ELO_REPLAY_FORMAT = $(if ($Format -like "*double*") { "double" } else { "single" }) + $(if ($Format -like "*uncursed*") { "_uncursed" } else { "" })
$env:ELO_REPLAY_SEED = "$Seed"
if ($OutputName) {
    $env:ELO_REPLAY_NAME = $OutputName
}
else {
    Remove-Item Env:\ELO_REPLAY_NAME -ErrorAction SilentlyContinue
}

Set-ReplayTrainerEnv -Prefix "T1" -Label $Trainer1
Set-ReplayTrainerEnv -Prefix "T2" -Label $Trainer2

Push-Location $GameDir
if ($UseDebugFlag) {
    $proc = Start-Process -FilePath ".\Game.exe" -ArgumentList "debug" -PassThru `
        -RedirectStandardOutput (Join-Path $ResultsDir "replay_stdout.log") `
        -RedirectStandardError  (Join-Path $ResultsDir "replay_stderr.log")
}
else {
    $proc = Start-Process -FilePath ".\Game.exe" -PassThru `
        -RedirectStandardOutput (Join-Path $ResultsDir "replay_stdout.log") `
        -RedirectStandardError  (Join-Path $ResultsDir "replay_stderr.log")
}
Pop-Location

"Launched PID $($proc.Id) -- result will land in vendor\tectonic-content\Analysis\replay_result.txt"
