#!/usr/bin/env python3
"""
Splices a targeted subset rerun's results back into the real per-format
result files, in place -- for correcting existing data (e.g. a trainer/AI
behavior fix that only invalidated some pairings) rather than creating a
new derived format the way build_uncursed_results.py does for "uncursed".

Input: elo_results_<fmt>_<subset_tag>_shard*.jsonl, produced by a
tournament.rb run with ELO_SUBSET_TRAINER_LABELS set (see
run_tournament.ps1/run_remote_parallel.ps1's -SubsetTrainerLabels) --
only pairings touching at least one of those trainer labels, for
whichever format(s) needed rerunning.

For each format:
  1. Back up every elo_results_<fmt>_shard*.jsonl (the file this script is
     about to modify) into results/backup_<timestamp>_<label>/ -- copies,
     not moves, so the live files stay in place and get corrected while
     the backup is purely a safety net.
  2. Read every elo_results_<fmt>_<subset_tag>_shard*.jsonl row, keyed by
     the pairing (trainer1, trainer2) regardless of order (format is
     already scoped by which file it's in).
  3. Walk every base elo_results_<fmt>_shard*.jsonl line; if its pairing
     has a subset replacement, splice the new row in over the old one.
  4. Any subset row that never matched an existing base pairing (pool
     changed since the base run, not just a correction) is appended to
     the first base shard file rather than silently dropped.
  5. Move the now-fully-consumed subset input files (results/status/
     attempting/etc) into the same backup directory -- not deleted, but
     out of the results dir, so a later discover_formats() scan can't
     pick up "<fmt>_<subset_tag>" as a phantom extra format.

Run once per rerun, after pulling all subset-run results
(pull_remote_results.ps1) and confirming every shard's status shows
finished:true.
"""
import argparse
import datetime
import glob
import json
import os
import shutil

import results_lib
from results_lib import REPO_ROOT

SUBSET_FILE_KINDS = (
    ("elo_results_{fmt}_shard*.jsonl", "results"),
    ("elo_status_{fmt}_shard*.json", "status"),
    ("elo_attempting_{fmt}_shard*.json", "attempting"),
    ("elo_crash_streaks_{fmt}_shard*.txt", "crash streak"),
    ("elo_turn_heartbeat_{fmt}_shard*.json", "turn heartbeat"),
)


def pair_key(row):
    return frozenset((row.get("trainer1"), row.get("trainer2")))


def make_backup_dir(label):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(REPO_ROOT, "results", f"backup_{timestamp}_{label}")
    os.makedirs(path, exist_ok=True)
    return path


def apply_subset_for_format(fmt, subset_tag, results_dir, backup_dir):
    subset_fmt = f"{fmt}_{subset_tag}"
    subset_rows = results_lib.load_results(subset_fmt, results_dir=results_dir, report_skipped=True)
    if not subset_rows:
        print(f"[{fmt}] no subset results found for '{subset_fmt}' under {results_dir} -- skipping.")
        return

    remaining = {pair_key(row): row for row in subset_rows}

    base_paths = sorted(glob.glob(os.path.join(results_dir, f"elo_results_{fmt}_shard*.jsonl")))
    base_paths = [p for p in base_paths if not results_lib._is_sidecar_file(p)]
    if not base_paths:
        print(f"[{fmt}] WARNING: no base elo_results_{fmt}_shard*.jsonl files found -- nothing to splice into.")
        return

    total_replaced = 0
    for path in base_paths:
        shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        changed = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            key = pair_key(row)
            if key in remaining:
                lines[i] = json.dumps(remaining.pop(key)) + "\n"
                changed = True
                total_replaced += 1
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)

    if remaining:
        target = base_paths[0]
        with open(target, "a", encoding="utf-8") as f:
            for row in remaining.values():
                f.write(json.dumps(row) + "\n")
        print(f"[{fmt}] {len(remaining)} subset row(s) had no matching base pairing -- appended to {target}")

    print(f"[{fmt}] replaced {total_replaced} row(s) across {len(base_paths)} shard file(s)")

    moved = 0
    for pattern, _label in SUBSET_FILE_KINDS:
        for p in glob.glob(os.path.join(results_dir, pattern.format(fmt=subset_fmt))):
            if results_lib._is_sidecar_file(p):
                continue
            shutil.move(p, os.path.join(backup_dir, os.path.basename(p)))
            moved += 1
    print(f"[{fmt}] moved {moved} consumed subset input file(s) into {backup_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--formats", default="singles,doubles,singles_uncursed,doubles_uncursed", metavar="LIST",
        help="Comma-separated real formats to apply the subset rerun to (default: all 4 real battled formats).",
    )
    parser.add_argument(
        "--subset-tag", default="subset", metavar="TAG",
        help="Tag used when launching the subset rerun (matches -SubsetTag on run_tournament.ps1/run_remote_parallel.ps1).",
    )
    parser.add_argument(
        "--label", default="subset_merge", metavar="LABEL",
        help="Label used in the backup directory name (results/backup_<timestamp>_<label>/).",
    )
    parser.add_argument(
        "--results-dir", default=results_lib.RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    args = parser.parse_args()

    backup_dir = make_backup_dir(args.label)
    print(f"Backup directory: {backup_dir}")

    for fmt in args.formats.split(","):
        fmt = fmt.strip()
        apply_subset_for_format(fmt, args.subset_tag, args.results_dir, backup_dir)


if __name__ == "__main__":
    main()
