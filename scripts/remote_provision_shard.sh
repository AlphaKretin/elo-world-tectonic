#!/usr/bin/env bash
# One-time setup for a fresh DigitalOcean droplet shard. Codifies the exact
# steps validated manually against the test droplet (209.38.18.140) --
# see [[project-cloud-distribution-validation]] for the why behind each
# step. Idempotent: safe to re-run (e.g. after a `git checkout --` reset)
# without re-doing already-done work, except the apt install (cheap/no-op
# if already installed) and the debug-compile pass (always re-run, cheap
# relative to a battle, and the only way to guarantee the compiled
# PluginScripts.rxdata/Data/*.dat actually reflect current source).
#
# Usage (run on the droplet, as root): ./remote_provision_shard.sh
set -euo pipefail

REPO_URL="https://github.com/AlphaKretin/Pokemon-Tectonic-Mods"
BRANCH="elo-tournament"
GAME_DIR="$HOME/elo-test"
DISPLAY_NUM=":100"

echo "=== Installing dependencies ==="
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    xvfb mesa-utils libgl1-mesa-dri libglx-mesa0 fluxbox x11-utils git

if [[ ! -d "$GAME_DIR/.git" ]]; then
    echo "=== Cloning $REPO_URL ($BRANCH) ==="
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$GAME_DIR"
else
    echo "=== $GAME_DIR already a git checkout, syncing to latest $BRANCH ==="
    # A prior run's compiled artifacts/results/errorlog are droplet-local
    # scratch, not anything worth preserving -- reset+clean so a shard that
    # was provisioned before the latest fix was pushed actually picks it up,
    # instead of silently running stale code forever (bit us on the last rerun).
    git -C "$GAME_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$GAME_DIR" checkout "$BRANCH"
    git -C "$GAME_DIR" reset --hard "origin/$BRANCH"
    git -C "$GAME_DIR" clean -fdx
fi

cd "$GAME_DIR"
chmod +x 'Game Linux.x86_64'
mkdir -p Analysis Changelogs results

echo "=== Starting Xvfb + fluxbox on $DISPLAY_NUM ==="
pkill -f "Xvfb $DISPLAY_NUM " 2>/dev/null || true
pkill -f "fluxbox" 2>/dev/null || true
sleep 1
setsid Xvfb "$DISPLAY_NUM" -screen 0 512x384x24 -nolisten tcp \
    < /dev/null > /tmp/xvfb.log 2>&1 < /dev/null &
disown
sleep 2
setsid env DISPLAY="$DISPLAY_NUM" fluxbox \
    < /dev/null > /tmp/fluxbox.log 2>&1 < /dev/null &
disown
sleep 2

echo "=== Debug+compile (PluginScripts.rxdata + PBS Data/*.dat) ==="
rm -f Analysis/compile_done.txt
setsid env DISPLAY="$DISPLAY_NUM" LIBGL_ALWAYS_SOFTWARE=1 ALSOFT_DRIVERS=null \
    ELO_TOURNAMENT=1 ELO_COMPILE_ONLY=1 \
    timeout -k 10 90 ./'Game Linux.x86_64' debug compile \
    < /dev/null > /tmp/compile.log 2>&1 < /dev/null
# Compile runs synchronously here (no trailing & ) since provisioning
# should fail loudly if it doesn't finish, unlike the watchdog's launches.
if [[ ! -f Analysis/compile_done.txt ]]; then
    echo "ERROR: compile_done.txt never appeared -- check /tmp/compile.log" >&2
    exit 1
fi
echo "Compile done: $(cat Analysis/compile_done.txt)"

echo "=== Validating with a single test battle ==="
rm -f Analysis/single_pairing_test.txt errorlog.txt
setsid env DISPLAY="$DISPLAY_NUM" LIBGL_ALWAYS_SOFTWARE=1 ALSOFT_DRIVERS=null \
    ELO_TOURNAMENT=1 ELO_TEST_SINGLE_PAIRING=1 \
    ELO_TEST_T1_TYPE=YOUNGSTER ELO_TEST_T1_NAME=Joey \
    ELO_TEST_T2_TYPE=HARLEQUIN ELO_TEST_T2_NAME=Vincenzi \
    ELO_TEST_SEED=2786941428 \
    timeout -k 5 40 ./'Game Linux.x86_64' \
    < /dev/null > /tmp/validate.log 2>&1 < /dev/null
sleep 1
if grep -q '"ok":true' Analysis/single_pairing_test.txt 2>/dev/null; then
    echo "=== Shard provisioned and validated OK ==="
    cat Analysis/single_pairing_test.txt
else
    echo "ERROR: validation battle did not report ok:true -- check /tmp/validate.log and Analysis/single_pairing_test.txt" >&2
    exit 1
fi
