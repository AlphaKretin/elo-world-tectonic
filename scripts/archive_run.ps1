# Archives the shared errorlog.txt, and optionally the current run's
# result/log files, instead of leaving them to accumulate indefinitely.
#
# errorlog.txt is shared across every shard process regardless of game
# directory (keyed by game title, not working directory), so it never
# resets on its own -- without this, errors from a previous code
# version sit mixed in with new ones, making it hard to tell what's
# actually new. Archived (by default) on every run_parallel.ps1
# launch, fresh start or resume alike.
#
# Result/log files (elo_results_*, elo_status_*, watchdog_*, etc.) are
# what makes a resume a *resume* -- archiving those discards progress,
# so that's opt-in via -IncludeResults, only for an intentional fresh
# start (e.g. after a fix that invalidates prior data), never automatic.
#
# Moves rather than deletes: old data might still be useful later (e.g.
# diagnosing a different bug), even when it's not valid for ELO ratings.
param(
    [string]$Label = "run",
    [switch]$IncludeResults
)

. (Join-Path $PSScriptRoot "archive_lib.ps1")

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results\local"

$errorLogPath = Join-Path $env:APPDATA "Pokemon Tectonic\errorlog.txt"
$haveErrorLog = (Test-Path $errorLogPath) -and (Get-Item $errorLogPath).Length -gt 0
$resultFiles = if ($IncludeResults) {
    Get-ChildItem -Path $ResultsDir -File | Where-Object {
        $_.Name -match '^(elo_results_|elo_status_|elo_attempting_|elo_crash_streaks_|elo_turn_heartbeat_|watchdog_|game_stdout_|game_stderr_|custom_trainer_|single_pairing_|batch_pairing_)'
    }
} else { @() }

if (-not $haveErrorLog -and -not $resultFiles) {
    Write-Output "Nothing to archive."
    return
}

$ArchiveDir = New-ArchiveDir -Label $Label

if ($resultFiles) {
    Write-Output "Archiving $($resultFiles.Count) result/log file(s) -> $ArchiveDir"
    $resultFiles | Move-Item -Destination $ArchiveDir
} elseif ($IncludeResults) {
    Write-Output "No result/log files to archive."
}

if ($haveErrorLog) {
    $dest = Join-Path $ArchiveDir "errorlog.txt"
    Write-Output "Archiving errorlog.txt ($((Get-Item $errorLogPath).Length) bytes) -> $dest"
    Move-Item -Path $errorLogPath -Destination $dest
} else {
    Write-Output "No errorlog.txt content to archive."
}

Write-Output "Done. Archived under $ArchiveDir"
