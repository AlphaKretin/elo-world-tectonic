#!/usr/bin/env python3
"""
Builds a synthetic "no curse influence anywhere" results file per base
format by merging the real round-robin (elo_results_<fmt>_shard*.jsonl)
with the curse-stripped format's real re-battled results
(elo_results_<fmt>_uncursed_shard*.jsonl -- see curse_stripping.rb).
Unlike ratings.py's --exclude-cursed (which just discards every
curse-flagged battle and leaves cursed trainers with no data at all), this
keeps a real, comparable result for every trainer by substituting in their
actual curse-stripped battles wherever fresh ones were simulated.

Written to elo_results_<fmt>_composite_shard0.jsonl next to the two source
formats, so it needs no changes anywhere else: ratings.py, best_worst.py,
etc. already discover and treat any "elo_results_<X>_shard*.jsonl" as a
format of its own via results_lib.discover_formats.

Merge rule per pairing (confirmed with Luna 2026-07-04):
  1. curse:false rows carry over unchanged.
  2. curse:true rows are replaced by the matching pairing's row in the
     _uncursed format's results, if one exists there (uncursedEdges only
     re-battles pairings where at least one side's stripped party actually
     changed -- see tournament.rb).
  3. curse:true rows with no _uncursed counterpart are pairings where
     stripping was a no-op for both sides (e.g. CURSE_NO_MERCY, confirmed
     inert -- see curse_stripping.rb's CURSE_INERT_TYPES) -- kept as-is,
     UNLESS either trainer is "identical_to_base" per curse_strip_diff.json
     (their stripped form duplicates another pool member exactly, so they're
     excluded from the _uncursed pool entirely as a redundant opponent --
     keeping their curse:true rows here would double-count that opponent).
  4. Every row from the _uncursed format is included.

Run after both the base format and its _uncursed counterpart have
complete result data (see project_phase_status.md for run status).
"""
import argparse
import json
import os

import results_lib
from results_lib import ANALYSIS_DIR, REPO_ROOT


def pair_key(row):
    return frozenset((row.get("trainer1"), row.get("trainer2")))


def build_composite(base_fmt, results_dir):
    uncursed_fmt = f"{base_fmt}_uncursed"
    base_rows = results_lib.load_results(base_fmt, results_dir=results_dir, report_skipped=True)
    uncursed_rows = results_lib.load_results(uncursed_fmt, results_dir=results_dir, report_skipped=True)
    if not base_rows:
        raise SystemExit(f"No results found for format '{base_fmt}' under {results_dir}.")
    if not uncursed_rows:
        raise SystemExit(f"No results found for format '{uncursed_fmt}' under {results_dir} -- run the curse-stripped tournament first.")

    diff = results_lib.load_curse_strip_diff()
    identical_to_base = {label for label, info in diff.items() if info.get("identical_to_base")}

    uncursed_pairs = {pair_key(r) for r in uncursed_rows}

    composite = []
    dropped_identical, superseded = 0, 0
    for row in base_rows:
        if not row.get("curse"):
            composite.append(row)
            continue
        if pair_key(row) in uncursed_pairs:
            superseded += 1
            continue
        t1, t2 = row.get("trainer1"), row.get("trainer2")
        if t1 in identical_to_base or t2 in identical_to_base:
            dropped_identical += 1
            continue
        composite.append(row)
    composite.extend(uncursed_rows)

    return composite, superseded, dropped_identical


def write_composite(fmt, rows, results_dir):
    path = os.path.join(results_dir, f"elo_results_{fmt}_composite_shard0.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--formats", default="singles,doubles", metavar="LIST",
        help="Comma-separated base formats to build a composite for (default: singles,doubles). "
             "Each needs both '<fmt>' and '<fmt>_uncursed' results already present.",
    )
    parser.add_argument(
        "--results-dir", default=results_lib.RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    args = parser.parse_args()

    for fmt in args.formats.split(","):
        fmt = fmt.strip()
        composite, superseded, dropped_identical = build_composite(fmt, args.results_dir)
        path = write_composite(fmt, composite, args.results_dir)
        print(f"[{fmt}] {len(composite)} rows -> {path} "
              f"({superseded} curse:true rows superseded by fresh _uncursed battles, "
              f"{dropped_identical} dropped as identical_to_base duplicates)")


if __name__ == "__main__":
    main()
