# Aggregate live status across all shards. Run in its own terminal and
# leave it open -- only reads status files, never touches the running
# Game.exe processes.
param(
    [string]$Format = "singles",
    [int]$ShardCount = 8,
    [int]$RefreshSeconds = 3
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"

$lastAttempting = @{}
$lastAttemptingChangedAt = @{}

while ($true) {
    Clear-Host
    Write-Output "ELO Tournament parallel status ($Format, $ShardCount shards) -- Ctrl+C to stop watching (does not stop the tournament)"
    Write-Output "================================================================"

    $totalDone = 0
    $totalAll  = 0
    $anyError  = $false

    for ($i = 0; $i -lt $ShardCount; $i++) {
        $suffix = "${Format}_shard$i"
        $statusPath = Join-Path $ResultsDir "elo_status_$suffix.json"
        $attemptingPath = Join-Path $ResultsDir "elo_attempting_$suffix.json"

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
