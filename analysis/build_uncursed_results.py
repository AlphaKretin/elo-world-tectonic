#!/usr/bin/env python3
"""
Builds the "uncursed" tournament format's actual results per base format by
merging the real round-robin (elo_results_<fmt>_shard*.jsonl) with the
curse-stripped format's raw re-battled results
(elo_results_<fmt>_uncursed_raw_shard*.jsonl -- see curse_stripping.rb).
Unlike ratings.py's --exclude-cursed (which just discards every
curse-flagged battle and leaves cursed trainers with no data at all), this
keeps a real, comparable result for every trainer by substituting in their
actual curse-stripped battles wherever fresh ones were simulated.

Written to elo_results_<fmt>_uncursed_shard0.jsonl next to the two source
formats, so it needs no changes anywhere else: ratings.py, best_worst.py,
etc. already discover and treat any "elo_results_<X>_shard*.jsonl" as a
format of its own via results_lib.discover_formats.

The raw curse-stripped subset (elo_results_<fmt>_uncursed_raw_shard*.jsonl)
is only ever an input here -- it's a partial re-battled set, not a full
round robin, so results_lib excludes it from default ratings generation
entirely (see results_lib.RAW_ONLY_SUFFIX). Its filename uses "_raw"
specifically to avoid colliding with this script's own "_uncursed" output:
pull_remote_results.ps1 fetches the raw curse-stripped tournament run under
its actual format name ("singles_uncursed"/"doubles_uncursed"), so after
every pull, rename those raw shards to "_uncursed_raw" BEFORE running this
script, or the next pull will silently clobber this script's merged output
with fresh raw shard data (both would otherwise be named
elo_results_<fmt>_uncursed_shard0.jsonl).

Merge rule per pairing (confirmed with Luna 2026-07-04):
  1. curse:false rows carry over unchanged.
  2. curse:true rows are replaced by the matching pairing's row in the
     raw curse-stripped results, if one exists there (uncursedEdges only
     re-battles pairings where at least one side's stripped party actually
     changed -- see tournament.rb).
  3. curse:true rows with no raw counterpart are pairings where stripping
     was a no-op for both sides (e.g. CURSE_NO_MERCY, confirmed inert --
     see curse_stripping.rb's CURSE_INERT_TYPES) -- kept as-is, UNLESS
     either trainer is "identical_to_base" per curse_strip_diff.json (their
     stripped form duplicates another pool member exactly, so they're
     excluded from the uncursed pool entirely as a redundant opponent --
     keeping their curse:true rows here would double-count that opponent).
  4. Every row from the raw curse-stripped results is included.

Run after both the base format and its raw curse-stripped counterpart have
complete result data (see project_phase_status.md for run status).
"""
import argparse
import json
import os

import results_lib
from results_lib import ANALYSIS_DIR, REPO_ROOT


def pair_key(row):
    return frozenset((row.get("trainer1"), row.get("trainer2")))


def build_uncursed(base_fmt, results_dir):
    raw_fmt = f"{base_fmt}{results_lib.RAW_ONLY_SUFFIX}"
    base_rows = results_lib.load_results(base_fmt, results_dir=results_dir, report_skipped=True)
    raw_rows = results_lib.load_results(raw_fmt, results_dir=results_dir, report_skipped=True)
    if not base_rows:
        raise SystemExit(f"No results found for format '{base_fmt}' under {results_dir}.")
    if not raw_rows:
        raise SystemExit(
            f"No results found for format '{raw_fmt}' under {results_dir} -- run the curse-stripped "
            f"tournament first, then rename its output shards to that suffix."
        )

    diff = results_lib.load_curse_strip_diff()
    identical_to_base = {label for label, info in diff.items() if info.get("identical_to_base")}

    raw_pairs = {pair_key(r) for r in raw_rows}

    merged = []
    dropped_identical, superseded = 0, 0
    for row in base_rows:
        if not row.get("curse"):
            merged.append(row)
            continue
        if pair_key(row) in raw_pairs:
            superseded += 1
            continue
        t1, t2 = row.get("trainer1"), row.get("trainer2")
        if t1 in identical_to_base or t2 in identical_to_base:
            dropped_identical += 1
            continue
        merged.append(row)
    merged.extend(raw_rows)

    return merged, superseded, dropped_identical


def write_uncursed(fmt, rows, results_dir):
    path = os.path.join(results_dir, f"elo_results_{fmt}_uncursed_shard0.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--formats", default="singles,doubles", metavar="LIST",
        help="Comma-separated base formats to build uncursed results for (default: singles,doubles). "
             "Each needs both '<fmt>' and '<fmt>_uncursed_raw' results already present.",
    )
    parser.add_argument(
        "--results-dir", default=results_lib.RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    args = parser.parse_args()

    for fmt in args.formats.split(","):
        fmt = fmt.strip()
        merged, superseded, dropped_identical = build_uncursed(fmt, args.results_dir)
        path = write_uncursed(fmt, merged, args.results_dir)
        print(f"[{fmt}] {len(merged)} rows -> {path} "
              f"({superseded} curse:true rows superseded by fresh curse-stripped battles, "
              f"{dropped_identical} dropped as identical_to_base duplicates)")


if __name__ == "__main__":
    main()
