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
# each format runs to completion, then (if another format follows) does a
# fresh debug-compile before moving on, entirely self-contained on this
# one droplet. Deliberately does NOT wait for sibling droplets the way
# watch_singles_then_launch_doubles.ps1 does locally -- that script waits
# for *all* local shards because they share one vendor/tectonic-content
# directory and a recompile's robocopy /MIR would race a still-running
# sibling. Each droplet has its own independent git checkout, so that
# race doesn't exist remotely: every shard can move on to the next format
# the moment *it* finishes, with zero cross-droplet coordination and zero
# dependency on the control machine staying on after launch.
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

recompile() {
    # Same debug-compile pass remote_provision_shard.sh does. Run between
    # formats so a code fix pushed mid-singles (e.g. a quarantine flag,
    # an AI no-op fix) is picked up for doubles without restarting anything
    # by hand -- mirrors watch_singles_then_launch_doubles.ps1's reason
    # for recompiling between formats locally.
    ensure_display
    rm -f "$GAME_DIR/Analysis/compile_done.txt"
    setsid env ELO_TOURNAMENT=1 ELO_COMPILE_ONLY=1 \
        timeout -k 10 90 ./'Game Linux.x86_64' debug compile \
        < /dev/null > "$RESULTS_DIR/recompile.log" 2>&1 < /dev/null
    if [[ ! -f "$GAME_DIR/Analysis/compile_done.txt" ]]; then
        echo "$(date -Iseconds)  WARNING: recompile marker never appeared -- check $RESULTS_DIR/recompile.log" >&2
    fi
}

run_format() {
    local format="$1"
    local suffix="${format}_shard${SHARD_INDEX}"
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
    if [[ $((idx + 1)) -lt ${#FORMAT_LIST[@]} ]]; then
        echo "$(date -Iseconds)  [shard${SHARD_INDEX}] '$fmt' finished -- recompiling before next format"
        recompile
    fi
done

echo "$(date -Iseconds)  [shard${SHARD_INDEX}] all formats finished. Watchdog exiting."
