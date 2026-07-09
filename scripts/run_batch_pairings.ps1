# Runs an arbitrary list of pairings from a manifest file -- the scripted
# wrapper for EloTournament.testBatchPairings! (see tournament.rb). Meant
# for ad hoc calibration/regression batches (e.g. rerunning a specific set
# of pairings after a behavior fix) that are too many for
# run_single_pairing.ps1's one-battle-per-launch cost to be worth paying,
# but aren't a full tournament run either.
#
# -ManifestPath is a tab-separated file, one pairing per line:
#   t1Type<TAB>t1Name<TAB>t1Version<TAB>t2Type<TAB>t2Name<TAB>t2Version<TAB>seed<TAB>battleMode
# battleMode is the engine's own "single"/"double"/"triple" literal (see
# AIBenchmark.runBattle's battleMode:), not this repo's "singles"/"doubles"
# ELO_FORMAT convention. Blank lines and lines starting with # are skipped.
#
# -ShardCount > 1 splits the manifest round-robin across that many local
# shard directories (run setup_shards.ps1 first) so independent Game.exe
# processes churn through the batch in parallel -- testBatchPairings!
# itself has no notion of sharding, so the split happens here, not in
# Ruby. -ShardCount 1 (default) runs the whole manifest as-is directly in
# vendor/tectonic-content, no shard dir needed.
#
# Each shard gets its own ELO_TEST_RESULTS_PATH (shared with
# run_single_pairing.ps1/run_custom_trainer.ps1) pointed straight at
# results\local\ instead of the shard's own Analysis\, so there's no
# shard-local file for a future setup_shards.ps1 -Recompile to wipe -- see
# run_custom_trainer.ps1's header comment for the incident that motivated
# that convention. Per-shard files are concatenated into one combined file
# once every shard exits.
#
# No timeout, same reasoning as run_custom_trainer.ps1: batch sizes here
# are small next to a real tournament run, so this just waits for every
# shard to exit on its own.
param(
    [Parameter(Mandatory)][string]$ManifestPath,
    [int]$ShardCount = 1
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results\local"
$ShardsRoot = Join-Path $RepoRoot "shards"
$ManifestPath = (Resolve-Path $ManifestPath).Path
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

$lines = Get-Content $ManifestPath | Where-Object {
    $t = $_.Trim()
    $t -and -not $t.StartsWith("#")
}
if ($lines.Count -eq 0) {
    Write-Output "No pairings found in $ManifestPath."
    exit 1
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

# Round-robin split rather than contiguous chunks -- if the manifest is
# grouped (e.g. all of one trainer's pairings together, then the next),
# contiguous chunks would put one shard on the fast/easy group and another
# on the slow/crash-prone group; round-robin spreads any such clustering
# evenly instead.
$shardLines = @{}
for ($i = 0; $i -lt $ShardCount; $i++) { $shardLines[$i] = New-Object System.Collections.Generic.List[string] }
for ($j = 0; $j -lt $lines.Count; $j++) { $shardLines[$j % $ShardCount].Add($lines[$j]) }

$procs = @()
for ($i = 0; $i -lt $ShardCount; $i++) {
    if ($shardLines[$i].Count -eq 0) { continue }

    $GameDir = if ($ShardCount -gt 1) { Join-Path $ShardsRoot "shard$i" } else { Join-Path $RepoRoot "vendor\tectonic-content" }
    $shardManifest = if ($ShardCount -gt 1) { Join-Path $ResultsDir "batch_pairing_manifest_${stamp}_shard$i.tsv" } else { $ManifestPath }
    if ($ShardCount -gt 1) { $shardLines[$i] | Set-Content $shardManifest }
    $suffix = if ($ShardCount -gt 1) { "_shard$i" } else { "" }
    $shardResult = Join-Path $ResultsDir "batch_pairing_results_${stamp}${suffix}.jsonl"

    $env:ELO_TOURNAMENT          = "1"
    $env:ELO_TEST_BATCH_PAIRINGS = $shardManifest
    $env:ELO_TEST_RESULTS_PATH   = $shardResult

    Push-Location $GameDir
    $proc = Start-Process -FilePath ".\Game.exe" -PassThru `
        -RedirectStandardOutput (Join-Path $ResultsDir "batch_pairing_stdout_${stamp}${suffix}.log") `
        -RedirectStandardError  (Join-Path $ResultsDir "batch_pairing_stderr_${stamp}${suffix}.log")
    Pop-Location

    $procs += [PSCustomObject]@{ Index = $i; Proc = $proc; ResultPath = $shardResult; PairingCount = $shardLines[$i].Count; Suffix = $suffix }
    Write-Output "Launched shard $i (PID $($proc.Id), $($shardLines[$i].Count) pairings) against $GameDir"
}

Remove-Item Env:\ELO_TOURNAMENT, Env:\ELO_TEST_BATCH_PAIRINGS, Env:\ELO_TEST_RESULTS_PATH -ErrorAction SilentlyContinue

while (($procs | Where-Object { -not $_.Proc.HasExited }).Count -gt 0) {
    Start-Sleep -Seconds 5
}

$combined = Join-Path $ResultsDir "batch_pairing_results_$stamp.jsonl"
$anyMissing = $false
foreach ($p in $procs) {
    if (-not (Test-Path $p.ResultPath)) {
        Write-Output "Shard $($p.Index) (PID $($p.Proc.Id), exit code $($p.Proc.ExitCode)) produced no results file -- check batch_pairing_stderr_${stamp}$($p.Suffix).log."
        $anyMissing = $true
        continue
    }
    if ($ShardCount -gt 1) { Get-Content $p.ResultPath | Add-Content $combined }
}

if ($ShardCount -eq 1) { $combined = $procs[0].ResultPath }

Write-Output ""
if ($anyMissing) {
    Write-Output "Done with errors -- see above. Partial results combined at $combined"
} else {
    Write-Output "Done. Combined results at $combined"
}
