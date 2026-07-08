#!/usr/bin/env python3
"""
Removes duplicate (trainer1, trainer2, format) rows from
elo_results_<format>_shard*.jsonl files (default: results/current/; use
--results-dir results/local/ for local shard data or results/remote/ for
a not-yet-promoted pull), keeping the first occurrence of each pairing.

Background: tournament.rb's resume is identity-based (readCompletedKeys
only looks at trainer1/trainer2/format). If a shard's watchdog gets resumed
without first confirming the previous process actually stopped (see
feedback_elo_tournament_test_harness.md's "always re-pause before resume"
lesson), two process sets can run against the same shard's result file at
once, each re-simulating and re-appending pairings the other already
finished. Because the seed is deterministically derived from the pairing
key (battleSeedFromKey), the duplicate rows are expected to -- and did, when
checked for elo_results_singles_shard0.jsonl -- agree exactly on seed and
result, differing only in incidental fields like time_s. So this is a safe
dedupe, not a data-quality problem: keeping either copy is equally correct,
and ratings.py currently double-counts every duplicated pairing since it
has no dedup step of its own.

Removed rows are never discarded -- they're appended to a sibling
<file>.duplicates_removed.jsonl next to the original, so nothing is lost if
this turns out to be wrong.

IMPORTANT: pause the tournament first and confirm 0 Game.exe / 0 watchdog
processes are running before running this. Use pause_tournament.ps1 for
local shards or pause_remote_tournament.ps1 for remote droplets. The shard
processes append to these exact files while live; rewriting the file out
from under a live writer can lose whatever it appends between your read
and write.

Usage:
    python dedupe_results.py [--dry-run] [--yes]
"""
import argparse
import glob
import json
import os

import results_lib

RESULTS_DIR = results_lib.RESULTS_DIR


def is_clean(obj):
    return not obj.get("had_error") and not obj.get("skipped")


def process_file(path, dry_run):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    groups = {}  # key -> list of (line, obj), in file order
    unparseable = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            unparseable.append(line)
            continue
        key = (obj.get("trainer1"), obj.get("trainer2"), obj.get("format"))
        groups.setdefault(key, []).append((line, obj))

    if not any(len(g) > 1 for g in groups.values()):
        return 0, 0

    keep, removed = list(unparseable), []
    unexplained = 0
    n_removed = 0
    for key, group in groups.items():
        if len(group) == 1:
            keep.append(group[0][0])
            continue

        # Prefer a clean (non-had_error, non-skipped) row over a bad one --
        # a duplicate pair can legitimately disagree when the first attempt
        # crashed/was skipped and a later resume produced a real result for
        # the same seed. Only treat it as worth flagging when we can't
        # explain the disagreement that way (e.g. two clean rows with
        # different results for the same seed, which shouldn't happen).
        clean_idx = [i for i, (_, obj) in enumerate(group) if is_clean(obj)]
        if len(clean_idx) >= 1:
            if len(clean_idx) > 1:
                results = {group[i][1].get("result") for i in clean_idx}
                seeds = {group[i][1].get("seed") for i in clean_idx}
                if len(results) > 1 or len(seeds) > 1:
                    unexplained += 1
            chosen_idx = clean_idx[0]
        else:
            chosen_idx = 0  # all copies are bad; nothing better to prefer

        keep.append(group[chosen_idx][0])
        for i, (line, _) in enumerate(group):
            if i != chosen_idx:
                removed.append(line)
                n_removed += 1

    if n_removed == 0:
        return 0, 0

    print(f"  {os.path.basename(path)}: removing {n_removed} duplicate row(s)"
          + (f" ({unexplained} pairing(s) had multiple *clean* rows disagreeing on seed/result!)" if unexplained else ""))
    if not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(keep)
        removed_path = path + ".duplicates_removed.jsonl"
        with open(removed_path, "a", encoding="utf-8") as f:
            f.writelines(removed)
    return n_removed, unexplained


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
    paths = [p for p in paths if ".duplicates_removed" not in p and ".had_error_removed" not in p]
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
    total_unexplained = 0
    for path in paths:
        removed, unexplained = process_file(path, args.dry_run)
        total += removed
        total_unexplained += unexplained

    verb = "Would remove" if args.dry_run else "Removed"
    print(f"{verb} {total} duplicate row(s) total across {len(paths)} file(s).")
    if total_unexplained:
        print(f"WARNING: {total_unexplained} pairing(s) had multiple clean rows disagreeing on seed/result -- review before trusting the fit.")
    if total and not args.dry_run:
        print("Re-run analysis/ratings.py (and downstream report/compare scripts) to pick up the clean data.")


if __name__ == "__main__":
    main()
