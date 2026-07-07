# Stops every running tournament watchdog -- run_tournament.ps1 (main
# round robin), run_custom_trainer.ps1, or run_bracket.ps1 -- and any
# Game.exe instances they launched, regardless of shard count or format.
#
# Order matters: watchdogs are stopped first, *then* Game.exe. Stopping
# Game.exe first races against the watchdog's own poll loop -- it notices
# its child died and relaunches a replacement before this script gets to
# the watchdog itself, leaving an orphaned Game.exe with no supervisor.
# (run_custom_trainer.ps1 doesn't relaunch on exit, but is included here
# so one script can pause any of the three run_*.ps1 launchers.)
#
# This must be invoked with -File (as a real script), not inlined via
# -Command, since an inline -Command string containing the literal text
# "run_tournament.ps1" (or the other two names) matches its own process's
# command line under the same filter used to find real watchdogs, causing
# it to stop itself mid-run before it can finish.

$watchdogs = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match 'run_tournament\.ps1|run_custom_trainer\.ps1|run_bracket\.ps1' }

if ($watchdogs) {
    Write-Output "Stopping $($watchdogs.Count) watchdog process(es)..."
    $watchdogs | ForEach-Object {
        Write-Output "  PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Output "No watchdog processes found."
}

Start-Sleep -Seconds 1

$games = Get-Process -Name Game -ErrorAction SilentlyContinue
if ($games) {
    Write-Output "Stopping $($games.Count) Game.exe process(es)..."
    $games | Stop-Process -Force -ErrorAction SilentlyContinue
} else {
    Write-Output "No Game.exe processes found."
}

Start-Sleep -Seconds 1

$remainingWatchdogs = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match 'run_tournament\.ps1|run_custom_trainer\.ps1|run_bracket\.ps1' }
$remainingGames = Get-Process -Name Game -ErrorAction SilentlyContinue

Write-Output ""
Write-Output "Watchdogs remaining: $($remainingWatchdogs.Count)"
Write-Output "Game.exe remaining:  $($remainingGames.Count)"
