# Launches remote_run_tournament.sh on every droplet in remote_hosts.txt,
# each with ShardIndex = its position in the file (0-based) and
# ShardCount = total host count -- mirrors run_parallel.ps1's local
# ShardIndex/ShardCount contract exactly (tournament.rb's pairing-pool
# partition is purely `i % SHARD_COUNT == SHARD_INDEX`, agnostic to
# whether shards run on one machine or across a fleet).
#
# Each launch is `setsid ... & disown` over a single non-interactive ssh
# call so it survives the ssh session closing -- see
# [[feedback-cross-tool-environment-gotchas]] on why plain `&disown`
# alone isn't enough (no controlling-terminal SIGHUP without setsid).
#
# Run setup_remote_shards.ps1 first. Doesn't archive each droplet's local
# errorlog.txt (~/elo-test/errorlog.txt) the way archive_run.ps1 does for
# the Windows AppData one -- those accumulate per-droplet and aren't
# pulled automatically; check via ssh if investigating a specific shard's
# errors.
# -Formats takes a comma-separated sequence, e.g. "singles,doubles" -- each
# droplet works through the whole sequence on its own (finish singles,
# recompile, start doubles) with no cross-droplet coordination and no
# dependency on this control machine staying on after launch. See
# remote_run_tournament.sh's header comment for why this is safe remotely
# even though the local equivalent (watch_singles_then_launch_doubles.ps1)
# waits for every shard before recompiling -- that local constraint comes
# from all 8 shards sharing one directory, which doesn't apply here.
param(
    [string]$Formats = "singles",
    [string]$HostsFile = (Join-Path $PSScriptRoot "remote_hosts.txt"),
    [int]$TurnStallTimeoutSeconds = 60,
    [int]$BattleStallTimeoutSeconds = 240,
    [int]$PollIntervalSeconds = 5,
    [int]$SampleGamesPerTrainer = 0,
    [int]$SampleSeed = 1
)

$hosts = @(Get-Content $HostsFile | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object { $_.Trim() })
if (-not $hosts) {
    Write-Output "No hosts found in $HostsFile"
    return
}
$ShardCount = $hosts.Count
Write-Output "Launching watchdogs (formats: $Formats) on $ShardCount droplet(s)..."

for ($i = 0; $i -lt $hosts.Count; $i++) {
    $thisHost = $hosts[$i]
    # No leading `cd && ...` here -- bash's trailing `&` binds to the whole
    # preceding `&&`-list, not just the last command, so `cd x && setsid y &`
    # backgrounds "cd x && setsid y" as ONE job and the wrapper shell never
    # returns until that whole job's fds close (cost real debugging time,
    # see [[feedback-cross-tool-environment-gotchas]]). remote_run_tournament.sh
    # already `cd`s to $GAME_DIR internally, so it's just invoked directly.
    $remoteCmd = "setsid ~/remote_run_tournament.sh " +
        "--formats $Formats --shard-index $i --shard-count $ShardCount " +
        "--turn-stall-timeout $TurnStallTimeoutSeconds " +
        "--battle-stall-timeout $BattleStallTimeoutSeconds " +
        "--poll-interval $PollIntervalSeconds "
    if ($SampleGamesPerTrainer -gt 0) {
        $remoteCmd += "--sample-games-per-trainer $SampleGamesPerTrainer --sample-seed $SampleSeed "
    }
    # One log per shard (not per-format) -- a single watchdog process now
    # spans the whole format sequence.
    $remoteCmd += "< /dev/null > ~/elo-test/results/watchdog_shard${i}.log 2>&1 < /dev/null & disown; echo launched"

    Write-Output "[shard $i / $thisHost] launching..."
    # results/ is already created by remote_provision_shard.sh -- no
    # `mkdir && $remoteCmd` prefix here, for the same reason $remoteCmd
    # itself avoids a leading `cd &&` (see comment above).
    & ssh -o StrictHostKeyChecking=accept-new "root@$thisHost" "$remoteCmd"
}

Write-Output ""
Write-Output "$ShardCount shard watchdog(s) launched. Use watch_remote_tournament.ps1 for aggregate live status."
