# Shared by run_remote_parallel.ps1 and supervise_remote_chunks.ps1, dot-
# sourced by both, so the ssh launch command for a chunk is defined in
# exactly one place. A host's first chunk (launched by run_remote_parallel.ps1)
# and every later chunk it picks up after finishing (launched by the
# supervisor) must build an identical command -- two independently
# maintained copies would be a subtle way to end up with a host's Nth
# chunk silently using different timeouts/formats than its first.
function Invoke-RemoteChunkLaunch {
    param(
        [Parameter(Mandatory)][string]$TargetHost,
        [Parameter(Mandatory)][int]$ShardIndex,
        [Parameter(Mandatory)][int]$ShardCount,
        [Parameter(Mandatory)][string]$Formats,
        [int]$TurnStallTimeoutSeconds = 60,
        [int]$BattleStallTimeoutSeconds = 240,
        [int]$PollIntervalSeconds = 5,
        [int]$SampleGamesPerTrainer = 0,
        [int]$SampleSeed = 1,
        [string]$SubsetTrainerLabels = "",
        [string]$SubsetPairsPath = "",
        [string]$SubsetTag = "subset",
        [int]$TurnTimeout = 0
    )

    # No leading `cd && ...` here -- bash's trailing `&` binds to the whole
    # preceding `&&`-list, not just the last command (see
    # [[feedback-cross-tool-environment-gotchas]]). remote_run_tournament.sh
    # already `cd`s to $GAME_DIR internally.
    $remoteCmd = "setsid ~/remote_run_tournament.sh " +
        "--formats $Formats --shard-index $ShardIndex --shard-count $ShardCount " +
        "--turn-stall-timeout $TurnStallTimeoutSeconds " +
        "--battle-stall-timeout $BattleStallTimeoutSeconds " +
        "--poll-interval $PollIntervalSeconds "
    if ($SampleGamesPerTrainer -gt 0) {
        $remoteCmd += "--sample-games-per-trainer $SampleGamesPerTrainer --sample-seed $SampleSeed "
    }
    if ($SubsetTrainerLabels) {
        # Single-quoted on the remote side -- SubsetTrainerLabels is a single
        # comma-separated argument that may contain spaces within a label
        # (e.g. "WILDPARTY_KOKO:of Conflict"), and single-quoting preserves
        # it as one bash argv entry without bash reinterpreting the spaces.
        $remoteCmd += "--subset-trainer-labels '$SubsetTrainerLabels' --subset-tag $SubsetTag "
    }
    if ($SubsetPairsPath) {
        # Path on the REMOTE host's own filesystem (not this control
        # machine) -- the manifest must already be there (e.g. scp'd up
        # alongside setup_remote_shards.ps1's initial sync) before launch.
        $remoteCmd += "--subset-pairs-path '$SubsetPairsPath' --subset-tag $SubsetTag "
    }
    if ($TurnTimeout -gt 0) {
        $remoteCmd += "--turn-timeout $TurnTimeout "
    }
    $remoteCmd += "< /dev/null > ~/elo-test/results/watchdog_shard${ShardIndex}.log 2>&1 < /dev/null & disown; echo launched"

    # -n: see setup_remote_shards.ps1's comment on the same flag -- prevents
    # ssh.exe hanging on a stdin EOF that never arrives in a scripted context.
    & ssh -n -o StrictHostKeyChecking=accept-new "root@$TargetHost" "$remoteCmd"
}
