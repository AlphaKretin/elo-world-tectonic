# Aggregate live status across all shards. Run in its own terminal and
# leave it open -- only reads status files, never touches the running
# Game.exe processes.
param(
    [string]$Format = "singles",
    [int]$ShardCount = 8,
    [int]$RefreshSeconds = 3
)

. (Join-Path $PSScriptRoot "_watch_common.ps1")

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"

$lastAttempting = @{}
$lastAttemptingChangedAt = @{}

while ($true) {
    Clear-Host
    Write-Output "ELO Tournament parallel status ($Format, $ShardCount shards) -- Ctrl+C to stop watching (does not stop the tournament)"
    Write-Output "================================================================"

    $doneByFormat = @{}
    $globalTotalByFormat = @{}
    $anyError  = $false

    for ($i = 0; $i -lt $ShardCount; $i++) {
        $suffix = "${Format}_shard$i"
        $statusPath = Join-Path $ResultsDir "elo_status_$suffix.json"
        $attemptingPath = Join-Path $ResultsDir "elo_attempting_$suffix.json"

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

        if (Test-Path $attemptingPath) {
            $current = Get-Content $attemptingPath -Raw
            if ($current -ne $lastAttempting[$i]) {
                $lastAttempting[$i] = $current
                $lastAttemptingChangedAt[$i] = Get-Date
            }
            $sinceChange = [int]((Get-Date) - $lastAttemptingChangedAt[$i]).TotalSeconds
            Write-Output "attempting (unchanged ${sinceChange}s): $current"
        }
    }

    Write-AggregateFooter $doneByFormat $globalTotalByFormat $anyError

    Start-Sleep -Seconds $RefreshSeconds
}
