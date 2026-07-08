#!/usr/bin/env python3
"""
One-off: splices the WSL2-rebattled replacements for the 8 had_error/skipped
rows (5 singles crash-skips, well 6 as counted 2026-07-04, + 2 doubles
DOCTOR:Renaldo had_error rows -- see project_resolved_bugs.md) back into
results/current/elo_results_<fmt>_shard*.jsonl (results_lib.RESULTS_DIR),
after a `pull_remote_results.ps1` run clobbered the previous local fix with
raw (pre-fix) remote data.

Reads results/local/backfill_batch_pairing_results.jsonl (testBatchPairings!
output, pulled from the WSL2 ~/elo-test checkout), converts each row to the
live tournament's row schema (trainerLabel strips "#0" for version 0,
"single"/"double" -> "singles"/"doubles", curse derived from
curse_strip_diff.json since testBatchPairings! doesn't compute it), and
replaces the matching (trainer1, trainer2, format) row in the shard file
it's found in. Writes a durable copy of the replacement rows to
results/archive/<timestamp>_backfill/backfilled_pairings.jsonl (mirrors
apply_subset_rerun.py's backup convention) so a future pull can't clobber
the only record of what was corrected.

Not idempotent-safe against re-running with different backfill data --
intended as a one-off tool, not a permanent pipeline step.
"""
import datetime
import json
import os

import results_lib
from results_lib import REPO_ROOT

BACKFILL_BATCH_PATH = os.path.join(REPO_ROOT, "results", "local", "backfill_batch_pairing_results.jsonl")


def make_permanent_record_path():
    # results/archive/<timestamp>_backfill/, not results/local/ -- this record
    # isn't shard-run scratch, it's a durable audit trail of exactly which
    # rows got corrected, so it follows apply_subset_rerun.py's own backup
    # convention instead: a timestamped folder under results/archive/, never a
    # pull_remote_results.ps1 target and never overwritten by a later run of
    # this same one-off tool.
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return os.path.join(REPO_ROOT, "results", "archive", f"{timestamp}_backfill", "backfilled_pairings.jsonl")


def normalize_label(raw_label):
    # testBatchPairings! always appends "#<version>", including "#0" -- the
    # live tournament's trainerLabel only appends when version > 0.
    if raw_label.endswith("#0"):
        return raw_label[:-2]
    return raw_label


def to_result_row(batch_row, cursed_labels):
    t1 = normalize_label(batch_row["t1"])
    t2 = normalize_label(batch_row["t2"])
    fmt = {"single": "singles", "double": "doubles"}[batch_row["format"]]
    return {
        "trainer1": t1,
        "trainer2": t2,
        "format": fmt,
        "seed": batch_row["seed"],
        "result": batch_row["result"],
        "rounds": batch_row["rounds"],
        "time_s": batch_row["time_s"],
        "had_error": batch_row["had_error"],
        "curse": t1 in cursed_labels or t2 in cursed_labels,
    }


def main():
    if not os.path.exists(BACKFILL_BATCH_PATH):
        raise SystemExit(f"{BACKFILL_BATCH_PATH} not found -- pull it from the WSL2 checkout's Analysis/batch_pairing_results.jsonl first.")

    with open(BACKFILL_BATCH_PATH, "r", encoding="utf-8") as f:
        batch_rows = [json.loads(line) for line in f if line.strip()]

    diff = results_lib.load_curse_strip_diff()
    cursed_labels = set(diff.keys())

    replacements = {}
    for br in batch_rows:
        if not br.get("ok"):
            print(f"SKIPPING non-ok batch row (still failing): {br}")
            continue
        row = to_result_row(br, cursed_labels)
        key = (row["trainer1"], row["trainer2"], row["format"])
        replacements[key] = row

    permanent_record_path = make_permanent_record_path()
    os.makedirs(os.path.dirname(permanent_record_path), exist_ok=True)
    with open(permanent_record_path, "w", encoding="utf-8") as f:
        for row in replacements.values():
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(replacements)} clean row(s) to {permanent_record_path}")

    remaining = dict(replacements)
    for fmt in ("singles", "doubles"):
        import glob
        for path in sorted(glob.glob(os.path.join(results_lib.RESULTS_DIR, f"elo_results_{fmt}_shard*.jsonl"))):
            if results_lib._is_sidecar_file(path):
                continue
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
                key = (row.get("trainer1"), row.get("trainer2"), row.get("format"))
                if key in remaining and (row.get("had_error") or row.get("skipped")):
                    lines[i] = json.dumps(remaining.pop(key)) + "\n"
                    changed = True
            if changed:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                print(f"Spliced clean row(s) into {path}")

    if remaining:
        print(f"WARNING: {len(remaining)} backfilled row(s) were never matched to a bad row on disk: {list(remaining.keys())}")
    else:
        print("All backfilled rows spliced successfully.")


if __name__ == "__main__":
    main()
