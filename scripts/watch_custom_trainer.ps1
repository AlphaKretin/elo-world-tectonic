# Aggregate live status for a run_custom_trainer.ps1 run. Separate from
# watch_parallel_tournament.ps1 on purpose -- that script reads
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

. (Join-Path $PSScriptRoot "_watch_common.ps1")

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results\local"

while ($true) {
    Clear-Host
    Write-Output "Custom trainer battle status ($Format, $ShardCount shards) -- Ctrl+C to stop watching"
    Write-Output "================================================================"

    $doneByFormat = @{}
    $globalTotalByFormat = @{}
    $anyError  = $false

    for ($i = 0; $i -lt $ShardCount; $i++) {
        $statusPath = Join-Path $ResultsDir "custom_trainer_status_${Format}_shard$i.json"

        Write-Output ""
        Write-Output "-- shard $i --"
        $d = Read-StatusJson $statusPath
        if ($d) {
            Show-StatusEntry $d $Format
            Add-StatusToAggregate -Data $d -Label $Format -GlobalTotalByFormat $globalTotalByFormat `
                -DoneByFormat $doneByFormat -AnyError ([ref]$anyError)
        } else {
            Write-Output "(no status yet)"
        }
    }

    Write-AggregateFooter $doneByFormat $globalTotalByFormat $anyError

    Start-Sleep -Seconds $RefreshSeconds
}
