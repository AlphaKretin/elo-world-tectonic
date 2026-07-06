# Aggregate live status for a run_custom_trainer.ps1 run. Separate from
# watch_tournament_parallel.ps1 on purpose -- that script reads
# results/elo_status_<format>_shard*.json, the *main* tournament's status
# files, which persist indefinitely across sessions for identity-based
# resume. Pointing it at a custom-trainer run showed stale leftover status
# from whatever the main tournament last did, since runCustomTrainerBattles!
# never touched those files in the first place. This instead reads
# results/custom_trainer_status_<format>_shard<N>.json -- deliberately
# *not* under any shard's own Analysis\ (see run_custom_trainer.ps1's
# header comment: a routine setup_shards.ps1 -Recompile robocopy /MIR
# silently deletes anything shard-local that the source doesn't have).
param(
    [string]$Format = "singles",
    [int]$ShardCount = 8,
    [int]$RefreshSeconds = 3
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"

while ($true) {
    Clear-Host
    Write-Output "Custom trainer battle status ($Format, $ShardCount shards) -- Ctrl+C to stop watching"
    Write-Output "================================================================"

    $totalDone = 0
    $totalAll  = 0
    $anyError  = $false

    for ($i = 0; $i -lt $ShardCount; $i++) {
        $statusPath = Join-Path $ResultsDir "custom_trainer_status_${Format}_shard$i.json"

        Write-Output ""
        Write-Output "-- shard $i --"
        if (Test-Path $statusPath) {
            $raw = Get-Content $statusPath -Raw
            Write-Output $raw
            if ($raw -match '"done":(\d+)')  { $totalDone += [int]$Matches[1] }
            if ($raw -match '"total":(\d+)') { $totalAll  += [int]$Matches[1] }
            if ($raw -match '"error":\{')    { $anyError = $true }
        } else {
            Write-Output "(no status yet)"
        }
    }

    Write-Output ""
    Write-Output "================================================================"
    if ($totalAll -gt 0) {
        $pct = [math]::Round($totalDone * 100.0 / $totalAll, 3)
        Write-Output "AGGREGATE: $totalDone / $totalAll ($pct%)"
    }
    if ($anyError) {
        Write-Output "*** At least one shard reports a top-level error -- check its status above. ***"
    }
    Write-Output "Last refreshed: $(Get-Date -Format o)"

    Start-Sleep -Seconds $RefreshSeconds
}
