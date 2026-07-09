#!/usr/bin/env python3
"""
Scans every on-disk result row for trainer1/trainer2 slot-order mismatches
against order_key.canonical_pair_order, and writes each format's mismatches
out as a SUBSET_PAIRS_PATH-compatible manifest -- see tournament.rb's
SUBSET_PAIRS_PATH/readSubsetPairs (plain tab-separated trainer1\ttrainer2,
one pairing per line, blank lines and #-comments skipped).

Background: trainer1/trainer2 slot assignment used to be pool-iteration-order
(arbitrary), but some battle mechanics are keyed to battler slot rather than
trainer identity, so slot order can change a battle's outcome (see
project_trainer_order_dependence memory). tournament.rb's buildPairs now
canonicalizes slot order via canonicalPairOrder before every pairing is
fought -- this script finds which *already-fought* pairings were fought in
the non-canonical order, so they can be resubmitted through the existing
remote subset-rerun pipeline (setup_remote_shards.ps1/run_remote_parallel.ps1
-SubsetPairsPath, then apply_subset_rerun.py to splice the corrected results
back into results/current in place).

Reads raw shard files directly (not the in-memory cursed+raw merge -- see
results_lib.py's module docstring), same as dedupe_results.py, since a
mismatched row needs fixing on disk regardless of which merged view would
show it.

Usage:
    python find_order_mismatches.py [--results-dir DIR] [--out-dir DIR]
"""
import argparse
import glob
import os

import order_key
import results_lib

RESULTS_DIR = results_lib.RESULTS_DIR


def find_mismatches_for_format(fmt, results_dir):
    rows = results_lib.load_shard_files(fmt, results_dir)
    mismatches = []
    for row in rows:
        t1, t2 = row.get("trainer1"), row.get("trainer2")
        if t1 is None or t2 is None:
            continue
        canonical = order_key.canonical_pair_order(t1, t2)
        if (t1, t2) != canonical:
            mismatches.append((t1, t2))
    return mismatches


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/current/)",
    )
    parser.add_argument(
        "--out-dir", default=None, metavar="DIR",
        help="Directory to write order_mismatch_pairs_<fmt>.tsv manifests into (default: --results-dir)",
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir
    out_dir = args.out_dir or args.results_dir
    os.makedirs(out_dir, exist_ok=True)

    formats = results_lib.discover_formats(results_dir=args.results_dir)
    if not formats:
        print(f"No elo_results_*_shard*.jsonl files found under {args.results_dir}.")
        return

    total = 0
    for fmt in formats:
        mismatches = find_mismatches_for_format(fmt, args.results_dir)
        total_rows = len(results_lib.load_shard_files(fmt, args.results_dir))
        if not mismatches:
            print(f"[{fmt}] 0 mismatches out of {total_rows} rows.")
            continue
        out_path = os.path.join(out_dir, f"order_mismatch_pairs_{fmt}.tsv")
        with open(out_path, "w", encoding="utf-8") as f:
            for t1, t2 in mismatches:
                f.write(f"{t1}\t{t2}\n")
        pct = 100.0 * len(mismatches) / total_rows if total_rows else 0.0
        print(f"[{fmt}] {len(mismatches)} mismatches out of {total_rows} rows ({pct:.1f}%) -> {out_path}")
        total += len(mismatches)

    print(f"Total: {total} mismatched pairing(s) across {len(formats)} format(s).")


if __name__ == "__main__":
    main()
