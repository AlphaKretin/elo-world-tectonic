# Battles a custom trainer (defined in a standalone PBS-formatted snippet --
# one [TrainerType,Name(,Version)] section, same syntax as one entry in
# PBS/trainers.txt) against every eligible trainer in the pool, across the
# local shards. See custom_trainer.rb / custom_trainer_battles.rb.
#
# No timeout -- waits as long as it takes. Battle volume here is tiny next
# to the main tournament (which runs for hours/overnight), but there's no
# principled bound to guess at either, so this just waits for every shard
# to exit on its own. custom_trainer_battles.rb is identity-resumable
# (skips pairings already in custom_trainer_results.jsonl), so if you do
# want to interrupt a run early (Ctrl+C, or kill the Game.exe processes
# yourself), re-running this script picks up wherever it left off instead
# of redoing finished battles.
#
# Run setup_shards.ps1 -Recompile first if custom_trainer*.rb changed
# since the shards were last synced.
#
# Results/status are written to results\ (this repo's, not any shard's own
# Analysis\), same convention as run_tournament.ps1 and for the same
# reason: setup_shards.ps1 -Recompile's robocopy /MIR mirrors each shard
# directory to exactly match vendor/tectonic-content, deleting anything in
# the shard dir that the source doesn't have -- a results file living
# inside a shard's own Analysis\ gets silently wiped by the next recompile.
# Learned this the hard way: an earlier version wrote
# shard<N>/Analysis/custom_trainer_results.jsonl directly and a routine
# -Recompile between runs deleted a completed 555-battle result set.
#
# -PbsFile can point anywhere (does not need to live under vendor/tectonic-content
# or any shard directory) -- every shard process reads it directly by its
# given path.
param(
    [Parameter(Mandatory)][string]$PbsFile,
    [string]$Format = "singles",
    [int]$ShardCount = 8
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results\local"
$ShardsRoot = Join-Path $RepoRoot "shards"
$PbsFile    = (Resolve-Path $PbsFile).Path

New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

$procs = @()
for ($i = 0; $i -lt $ShardCount; $i++) {
    $shardDir = Join-Path $ShardsRoot "shard$i"
    $env:ELO_TOURNAMENT                  = "1"
    $env:ELO_CUSTOM_TRAINER_BATTLES      = "1"
    $env:ELO_CUSTOM_TRAINER_PBS          = $PbsFile
    $env:ELO_FORMAT                      = $Format
    $env:ELO_SHARD_INDEX                 = "$i"
    $env:ELO_SHARD_COUNT                 = "$ShardCount"
    $env:ELO_CUSTOM_TRAINER_RESULTS_PATH = Join-Path $ResultsDir "custom_trainer_results_${Format}_shard$i.jsonl"
    $env:ELO_CUSTOM_TRAINER_STATUS_PATH  = Join-Path $ResultsDir "custom_trainer_status_${Format}_shard$i.json"

    Push-Location $shardDir
    $proc = Start-Process -FilePath ".\Game.exe" -PassThru `
        -RedirectStandardOutput (Join-Path $ResultsDir "custom_trainer_stdout_${Format}_shard$i.log") `
        -RedirectStandardError  (Join-Path $ResultsDir "custom_trainer_stderr_${Format}_shard$i.log")
    Pop-Location

    $procs += [PSCustomObject]@{ Index = $i; Proc = $proc; ShardDir = $shardDir }
    Write-Output "Launched shard $i (PID $($proc.Id)) against $shardDir"
}

Remove-Item Env:\ELO_TOURNAMENT, Env:\ELO_CUSTOM_TRAINER_BATTLES, Env:\ELO_CUSTOM_TRAINER_PBS, Env:\ELO_FORMAT, `
    Env:\ELO_SHARD_INDEX, Env:\ELO_SHARD_COUNT, Env:\ELO_CUSTOM_TRAINER_RESULTS_PATH, Env:\ELO_CUSTOM_TRAINER_STATUS_PATH `
    -ErrorAction SilentlyContinue

while (($procs | Where-Object { -not $_.Proc.HasExited }).Count -gt 0) {
    Start-Sleep -Seconds 5
}

Write-Output ""
Write-Output "Done. Per-shard results at results\custom_trainer_results_${Format}_shard<N>.jsonl"
