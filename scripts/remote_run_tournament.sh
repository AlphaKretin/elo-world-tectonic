#!/usr/bin/env bash
# Watchdog wrapper for the headless tournament, Linux/droplet side. Bash
# port of run_tournament.ps1 -- same two-timer stall detection, same
# relaunch-until-finished loop, same env-var contract with tournament.rb,
# just launching the headless Linux recipe (Xvfb + fluxbox + Mesa software
# GL + null OpenAL) validated against this game build instead of Game.exe.
# See [[project-cloud-distribution-validation]] for why each of those is
# needed -- in short: SDL_VIDEODRIVER=dummy fails outright (no GL support),
# Xvfb alone hangs forever with no window manager (fluxbox required),
# ALSOFT_DRIVERS=null is required separately from SDL_AUDIODRIVER=dummy
# since OpenAL and SDL audio are independent subsystems here.
#
# Two independent stall timers (mirrors run_tournament.ps1 exactly):
#   - turn-stall: resets whenever ELO_TURN_HEARTBEAT_PATH's content changes
#     (pbStartOfRoundPhase writes it every round). Catches a genuinely
#     stuck single turn.
#   - battle-stall: resets whenever ELO_ATTEMPTING_PATH's content changes
#     (a new battle started). Backstop for "progressing turn-by-turn but
#     the battle as a whole never ends."
#
# --formats takes a comma-separated sequence (e.g. "singles,doubles") --
# each format runs to completion, then the next one starts immediately on
# this same droplet, entirely self-contained, with zero cross-droplet
# coordination and zero dependency on the control machine staying on after
# launch. No recompile between formats: curse-stripping is a runtime
# ELO_FORMAT check, not compile-time (see tournament.rb's UNCURSED_RUN), so
# there's nothing a format switch needs picked up by a fresh compile. If
# you push a code fix mid-run, kill and relaunch to pick it up.
#
# Usage: run on the droplet itself, already cloned+compiled (see
# remote_provision_shard.sh). Not meant to be invoked over a single
# non-interactive ssh call directly -- wrap with setsid so it survives
# the ssh session closing (see [[feedback-cross-tool-environment-gotchas]]
# on why plain `&disown` isn't enough):
#   setsid env DISPLAY=:100 ... ./remote_run_tournament.sh --formats singles,doubles \
#     --shard-index 3 --shard-count 10 \
#     < /dev/null > results/watchdog_shard3.log 2>&1 < /dev/null &

set -u

FORMATS="singles"
TURN_STALL_TIMEOUT=60
BATTLE_STALL_TIMEOUT=240
POLL_INTERVAL=5
SHARD_INDEX=0
SHARD_COUNT=1
SAMPLE_GAMES_PER_TRAINER=0
SAMPLE_SEED=1
DISPLAY_NUM=":100"
SUBSET_TRAINER_LABELS=""
SUBSET_PAIRS_PATH=""
SUBSET_TAG="subset"
TURN_TIMEOUT=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --format) FORMATS="$2"; shift 2 ;;
        --formats) FORMATS="$2"; shift 2 ;;
        --turn-stall-timeout) TURN_STALL_TIMEOUT="$2"; shift 2 ;;
        --battle-stall-timeout) BATTLE_STALL_TIMEOUT="$2"; shift 2 ;;
        --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
        --shard-index) SHARD_INDEX="$2"; shift 2 ;;
        --shard-count) SHARD_COUNT="$2"; shift 2 ;;
        --sample-games-per-trainer) SAMPLE_GAMES_PER_TRAINER="$2"; shift 2 ;;
        --sample-seed) SAMPLE_SEED="$2"; shift 2 ;;
        --display) DISPLAY_NUM="$2"; shift 2 ;;
        # See tournament.rb's SUBSET_TRAINER_LABELS -- restricts this run to
        # only pairings touching one of these trainer labels, and tags the
        # results/status/etc filenames with "_$SUBSET_TAG" so this partial
        # set never collides with the format's own full-round-robin file.
        --subset-trainer-labels) SUBSET_TRAINER_LABELS="$2"; shift 2 ;;
        # See tournament.rb's SUBSET_PAIRS_PATH -- restricts this run to an
        # exact list of pairings instead of every pairing touching a label.
        # The path is resolved on THIS host, so the manifest must already
        # exist here (e.g. under $GAME_DIR/Analysis/) before launch --
        # nothing in this script uploads it. Accepts either one plain path
        # (used for every format in --formats, mirroring run_tournament.ps1's
        # -SubsetPairsPath exactly) or a "format=path,format=path" list when
        # different formats' timed-out pairings live in different manifests
        # -- see resolve_subset_pairs_path() below. A format missing from
        # the map gets no subset restriction at all.
        --subset-pairs-path) SUBSET_PAIRS_PATH="$2"; shift 2 ;;
        --subset-tag) SUBSET_TAG="$2"; shift 2 ;;
        --turn-timeout) TURN_TIMEOUT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

GAME_DIR="$HOME/elo-test"
RESULTS_DIR="$GAME_DIR/results"
mkdir -p "$RESULTS_DIR"

export DISPLAY="$DISPLAY_NUM"
export LIBGL_ALWAYS_SOFTWARE=1
export ALSOFT_DRIVERS=null

ensure_display() {
    # Idempotent: provisioning already starts these, but a droplet reboot
    # or an earlier crash could leave them dead. pgrep -f matches the
    # whole command line, not just argv[0], so this is safe to call
    # every relaunch without spawning duplicates.
    if ! pgrep -f "Xvfb $DISPLAY_NUM " > /dev/null; then
        setsid Xvfb "$DISPLAY_NUM" -screen 0 512x384x24 -nolisten tcp \
            < /dev/null > "$RESULTS_DIR/xvfb.log" 2>&1 < /dev/null &
        disown
        sleep 2
    fi
    if ! DISPLAY="$DISPLAY_NUM" pgrep -f "fluxbox" > /dev/null; then
        setsid env DISPLAY="$DISPLAY_NUM" fluxbox \
            < /dev/null > "$RESULTS_DIR/fluxbox.log" 2>&1 < /dev/null &
        disown
        sleep 2
    fi
}

# Mirrors run_tournament.ps1's Resolve-SubsetPairsPathForFormat /
# _chunk_queue.ps1's ConvertFrom-FormatKeyedOverrides: a bare
# $SUBSET_PAIRS_PATH (no "=") applies unchanged to every format; a
# "format=path,format=path" list resolves per format, with a format missing
# from the map getting no restriction. Prints the resolved path (possibly
# empty) to stdout -- call as `local p; p=$(resolve_subset_pairs_path "$fmt")`.
resolve_subset_pairs_path() {
    local format="$1"
    if [[ -z "$SUBSET_PAIRS_PATH" ]]; then
        echo ""
        return
    fi
    if [[ "$SUBSET_PAIRS_PATH" != *=* ]]; then
        echo "$SUBSET_PAIRS_PATH"
        return
    fi
    local IFS=','
    local entry
    for entry in $SUBSET_PAIRS_PATH; do
        local key="${entry%%=*}"
        local value="${entry#*=}"
        if [[ "$key" == "$format" ]]; then
            echo "$value"
            return
        fi
    done
    echo ""
}

run_format() {
    local format="$1"
    local resolved_subset_pairs_path
    resolved_subset_pairs_path=$(resolve_subset_pairs_path "$format")
    # format_tag (not format) drives every path -- keeps ELO_FORMAT itself
    # as the real format (so battle mode/curse stripping/etc behave
    # normally) while a subset run's files land under a distinct name.
    local format_tag="$format"
    if [[ -n "$SUBSET_TRAINER_LABELS" || -n "$resolved_subset_pairs_path" ]]; then
        format_tag="${format}_${SUBSET_TAG}"
    fi
    local suffix="${format_tag}_shard${SHARD_INDEX}"
    local results_path="$RESULTS_DIR/elo_results_${suffix}.jsonl"
    local status_path="$RESULTS_DIR/elo_status_${suffix}.json"
    local attempting_path="$RESULTS_DIR/elo_attempting_${suffix}.json"
    local crash_streak_path="$RESULTS_DIR/elo_crash_streaks_${suffix}.txt"
    local heartbeat_path="$RESULTS_DIR/elo_turn_heartbeat_${suffix}.json"

    export ELO_TOURNAMENT=1
    export ELO_FORMAT="$format"
    export ELO_SHARD_INDEX="$SHARD_INDEX"
    export ELO_SHARD_COUNT="$SHARD_COUNT"
    export ELO_RESULTS_PATH="$results_path"
    export ELO_STATUS_PATH="$status_path"
    export ELO_ATTEMPTING_PATH="$attempting_path"
    export ELO_CRASH_STREAK_PATH="$crash_streak_path"
    export ELO_TURN_HEARTBEAT_PATH="$heartbeat_path"
    if [[ "$SAMPLE_GAMES_PER_TRAINER" -gt 0 ]]; then
        export ELO_SAMPLE_GAMES_PER_TRAINER="$SAMPLE_GAMES_PER_TRAINER"
        export ELO_SAMPLE_SEED="$SAMPLE_SEED"
    else
        unset ELO_SAMPLE_GAMES_PER_TRAINER ELO_SAMPLE_SEED
    fi
    if [[ -n "$SUBSET_TRAINER_LABELS" ]]; then
        export ELO_SUBSET_TRAINER_LABELS="$SUBSET_TRAINER_LABELS"
    else
        unset ELO_SUBSET_TRAINER_LABELS
    fi
    if [[ -n "$resolved_subset_pairs_path" ]]; then
        export ELO_SUBSET_PAIRS_PATH="$resolved_subset_pairs_path"
    else
        unset ELO_SUBSET_PAIRS_PATH
    fi
    if [[ "$TURN_TIMEOUT" -gt 0 ]]; then
        export ELO_TURN_TIMEOUT="$TURN_TIMEOUT"
    else
        unset ELO_TURN_TIMEOUT
    fi

    is_finished() {
        [[ -f "$status_path" ]] && grep -q '"finished":true' "$status_path"
    }

    while ! is_finished; do
        ensure_display

        setsid stdbuf -oL -eL ./'Game Linux.x86_64' \
            < /dev/null > "$RESULTS_DIR/game_stdout_${suffix}.log" 2> "$RESULTS_DIR/game_stderr_${suffix}.log" < /dev/null &
        GAME_PID=$!
        disown

        echo "$(date -Iseconds)  [$suffix] launched Game Linux.x86_64 (PID $GAME_PID)"

        last_battle_progress_at=$(date +%s)
        last_attempting_snapshot=""
        last_turn_progress_at=$(date +%s)
        last_heartbeat_snapshot=""

        while kill -0 "$GAME_PID" 2>/dev/null; do
            sleep "$POLL_INTERVAL"

            if [[ -f "$attempting_path" ]]; then
                current=$(cat "$attempting_path" 2>/dev/null)
                if [[ "$current" != "$last_attempting_snapshot" ]]; then
                    last_attempting_snapshot="$current"
                    last_battle_progress_at=$(date +%s)
                    # New battle => round count resets too.
                    last_turn_progress_at=$(date +%s)
                    last_heartbeat_snapshot=""
                fi
            fi

            if [[ -f "$heartbeat_path" ]]; then
                current_heartbeat=$(cat "$heartbeat_path" 2>/dev/null)
                if [[ "$current_heartbeat" != "$last_heartbeat_snapshot" ]]; then
                    last_heartbeat_snapshot="$current_heartbeat"
                    last_turn_progress_at=$(date +%s)
                fi
            fi

            now=$(date +%s)
            turn_stalled=$(( now - last_turn_progress_at ))
            battle_stalled=$(( now - last_battle_progress_at ))

            if [[ "$turn_stalled" -gt "$TURN_STALL_TIMEOUT" ]]; then
                echo "$(date -Iseconds)  [$suffix] turn stalled ${turn_stalled}s (heartbeat: $last_heartbeat_snapshot) on: $last_attempting_snapshot -- killing PID $GAME_PID"
                kill -9 "$GAME_PID" 2>/dev/null
                break
            fi
            if [[ "$battle_stalled" -gt "$BATTLE_STALL_TIMEOUT" ]]; then
                echo "$(date -Iseconds)  [$suffix] battle stalled ${battle_stalled}s on: $last_attempting_snapshot -- killing PID $GAME_PID"
                kill -9 "$GAME_PID" 2>/dev/null
                break
            fi
        done

        if ! kill -0 "$GAME_PID" 2>/dev/null; then
            wait "$GAME_PID" 2>/dev/null
            echo "$(date -Iseconds)  [$suffix] Game Linux.x86_64 exited (code $?)"
        fi

        sleep 2
    done

    echo "$(date -Iseconds)  [$suffix] watchdog stopping for format '$format'. Status:"
    [[ -f "$status_path" ]] && cat "$status_path"
}

cd "$GAME_DIR" || exit 1

IFS=',' read -ra FORMAT_LIST <<< "$FORMATS"
for idx in "${!FORMAT_LIST[@]}"; do
    fmt="${FORMAT_LIST[$idx]}"
    echo "$(date -Iseconds)  [shard${SHARD_INDEX}] starting format '$fmt' (${idx}/${#FORMAT_LIST[@]})"
    run_format "$fmt"
done

echo "$(date -Iseconds)  [shard${SHARD_INDEX}] all formats finished. Watchdog exiting."
