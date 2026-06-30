# Stops every running remote watchdog (remote_run_tournament.sh) and any
# Game Linux.x86_64 instances they launched, on every droplet in
# remote_hosts.txt. Same ordering rationale as pause_tournament.ps1:
# watchdog first, *then* the game process -- killing the game process
# first races against the watchdog's own poll loop noticing its child
# died and relaunching a replacement before this script gets to the
# watchdog itself.
#
# Explicitly excludes $$ (the remote bash -c's own PID) from each kill
# loop -- pgrep -f matches by full command line, and that command line
# necessarily contains the literal search pattern text (e.g. "Game
# Linux.x86_64") as part of *this script's own remote invocation*, so a
# naive `pkill -f 'Game Linux.x86_64'` matches and kills its own invoking
# shell, sometimes before it finishes killing the real target (same
# self-match footgun pause_tournament.ps1's own comment already documents
# for the local/-Command case -- hit the remote equivalent for real
# during testing: the watchdog died but the game process survived).
param(
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt")
)

$hostList = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hostList) {
    Write-Output "No hosts found in $HostsFile"
    return
}

$RemoteKillScript = @'
for pid in $(pgrep -f remote_run_tournament.sh); do [ "$pid" != "$$" ] && kill -9 "$pid"; done
sleep 1
for pid in $(pgrep -f "Game Linux.x86_64"); do [ "$pid" != "$$" ] && kill -9 "$pid"; done
sleep 1
echo remaining:
pgrep -fa "remote_run_tournament.sh|Game Linux.x86_64" | grep -v "^$$ " || echo none
'@

$hostList | ForEach-Object -ThrottleLimit $hostList.Count -Parallel {
    $thisHost = $_
    $script = $using:RemoteKillScript
    Write-Output "[$thisHost] stopping watchdog..."
    & ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$thisHost" $script 2>&1 |
        ForEach-Object { "[$thisHost] $_" }
}

Write-Output ""
Write-Output "Done. Review each host's 'remaining:' line above -- should say 'none'."
