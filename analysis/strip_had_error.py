#!/usr/bin/env python3
"""
Removes had_error:true rows from elo_results_<format>_shard*.jsonl files
(default: results/current/; use --results-dir results/local/ for local
shard data or results/remote/ for a not-yet-promoted pull) so a future
resumed run re-attempts those exact pairings cleanly.

Background: tournament.rb flags any battle where errorlog.txt grew during
the call as had_error:true (engine hit a recoverable error mid-battle, e.g.
the boss-AI nil-sprite crashes under the headless no-UI scene -- see
PokeBattle_DebugSceneNoLogging / pbDisplayBossNarration). ratings.py now
excludes had_error rows from the Bradley-Terry fit, but that alone *removes*
that pairing's data point rather than getting a clean one. Since
tournament.rb's resume is identity-based (readCompletedKeys only looks at
trainer1/trainer2/format, not had_error) and the seed is deterministically
derived from that same key (battleSeedFromKey), simply deleting a
had_error:true row from a shard's results file is enough: the next resume
of that shard re-attempts the exact same pairing with the exact same seed
and appends a fresh result.

Removed rows are never discarded -- they're appended to a sibling
<file>.had_error_removed.jsonl next to the original, so nothing is lost if
this turns out to be wrong.

IMPORTANT: pause the tournament first and confirm 0 Game.exe / 0 watchdog
processes are running before running this. Use pause_tournament.ps1 for
local shards or pause_remote_tournament.ps1 for remote droplets. The shard
processes append to these exact files while live; rewriting the file out
from under a live writer can lose whatever it appends between your read
and write.

Usage:
    python strip_had_error.py [--dry-run] [--yes]
"""
import argparse
import glob
import json
import os

import results_lib

RESULTS_DIR = results_lib.RESULTS_DIR


def process_file(path, dry_run):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    keep, removed = [], []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            keep.append(line)  # leave unparseable lines untouched
            continue
        (removed if obj.get("had_error") else keep).append(line)

    if not removed:
        return 0

    print(f"  {os.path.basename(path)}: removing {len(removed)} had_error row(s)")
    if not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(keep)
        removed_path = path + ".had_error_removed.jsonl"
        with open(removed_path, "a", encoding="utf-8") as f:
            f.writelines(removed)
    return len(removed)


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report what would change without touching files")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/current/; use results/local/ or results/remote/ for not-yet-promoted data)",
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, "elo_results_*_shard*.jsonl")))
    paths = [p for p in paths if not p.endswith(".had_error_removed.jsonl")]
    if not paths:
        print(f"No elo_results_*_shard*.jsonl files found under {RESULTS_DIR}.")
        return

    if not args.dry_run and not args.yes:
        print("This rewrites result files in place. Make sure the tournament is")
        print("paused (pause_tournament.ps1 or pause_remote_tournament.ps1,")
        print("verify 0 Game.exe/watchdog) before continuing.")
        if input("Proceed? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return

    total = 0
    for path in paths:
        total += process_file(path, args.dry_run)

    verb = "Would remove" if args.dry_run else "Removed"
    print(f"{verb} {total} had_error row(s) total across {len(paths)} file(s).")
    if total and not args.dry_run:
        print("Resume the tournament normally; those pairings will be re-attempted.")


if __name__ == "__main__":
    main()
