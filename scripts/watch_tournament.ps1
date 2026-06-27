# Live activity display for a running tournament. Run this in its own
# terminal window and leave it open -- it just reads status files and
# redraws, it doesn't touch the running Game.exe process at all.
param(
    [string]$Format = "singles",
    [int]$RefreshSeconds = 2
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results"
$StatusPath     = Join-Path $ResultsDir "elo_status_$Format.json"
$AttemptingPath = Join-Path $ResultsDir "elo_attempting_$Format.json"

$lastAttempting = $null
$lastAttemptingChangedAt = Get-Date

while ($true) {
    Clear-Host
    Write-Output "ELO Tournament live status ($Format) -- refreshing every ${RefreshSeconds}s, Ctrl+C to stop watching (does not stop the tournament)"
    Write-Output "================================================================"
    Write-Output ""

    if (Test-Path $StatusPath) {
        Write-Output "STATUS ($StatusPath):"
        Write-Output (Get-Content $StatusPath -Raw)
    } else {
        Write-Output "(no status file yet)"
    }
    Write-Output ""

    if (Test-Path $AttemptingPath) {
        $current = Get-Content $AttemptingPath -Raw
        if ($current -ne $lastAttempting) {
            $lastAttempting = $current
            $lastAttemptingChangedAt = Get-Date
        }
        $sinceChange = [int]((Get-Date) - $lastAttemptingChangedAt).TotalSeconds
        Write-Output "CURRENTLY ATTEMPTING (unchanged for ${sinceChange}s):"
        Write-Output $current
        if ($sinceChange -gt 60) {
            Write-Output ""
            Write-Output "*** Over 60s on the same battle -- likely stalled. The watchdog (if running) will kill and retry it. ***"
        }
    } else {
        Write-Output "(no attempting file yet)"
    }

    Write-Output ""
    Write-Output "Last refreshed: $(Get-Date -Format o)"
    Start-Sleep -Seconds $RefreshSeconds
}
