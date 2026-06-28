#!/usr/bin/env python3
"""
Bradley-Terry trainer ratings from ELO Tournament battle results.

Reads every results/elo_results_<format>_shard*.jsonl, fits one-hot
±1 logistic regression per format (Bradley-Terry), and writes a sorted
leaderboard (CSV + JSON) per format to analysis/.

Draws (result code 5) count toward each trainer's draw/battle totals but
are excluded from the regression itself -- plain Bradley-Terry models a
binary win/loss outcome, and elo_world's original implementation (which
this ports) didn't model draws either. Skipped pairings (result: null)
and battles flagged had_error (engine hit a recoverable error mid-battle,
outcome may be corrupted -- see tournament.rb) are excluded entirely.

Running this against a partial, still-in-progress tournament is fine:
Bradley-Terry only needs *a* connected set of results, not all of them,
and re-running later as more results come in just refines the fit.
"""
import argparse
import csv
import glob
import json
import os
from collections import defaultdict

import numpy as np
from scipy.sparse import coo_matrix
from sklearn.linear_model import LogisticRegression

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))

WIN, LOSS, DRAW = 1, 2, 5

# rating = coefficient * ELO_SCALE + ELO_BASE, the standard logistic-regression
# Elo conversion (173 ~= 400 / ln(10), matching the usual Elo logistic curve).
ELO_SCALE = 173
ELO_BASE = 1500


def discover_formats():
    formats = set()
    for path in glob.glob(os.path.join(RESULTS_DIR, "elo_results_*_shard*.jsonl")):
        name = os.path.basename(path)
        # elo_results_<format>_shard<N>.jsonl
        middle = name[len("elo_results_"):-len(".jsonl")]
        fmt = middle.rsplit("_shard", 1)[0]
        formats.add(fmt)
    return sorted(formats)


def load_results(fmt):
    rows = []
    skipped_lines = 0
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, f"elo_results_{fmt}_shard*.jsonl"))):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Result files may be actively appended to by a live
                # tournament run while this reads them; a line caught
                # mid-write is incomplete JSON, not a real data problem.
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped_lines += 1
    if skipped_lines:
        print(f"  (skipped {skipped_lines} unparseable line(s), likely caught mid-write)")
    return rows


def compute_ratings(fmt):
    rows = load_results(fmt)

    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "draws": 0, "battles": 0})
    fit_rows = []  # (trainer1, trainer2, target) for the regression

    for r in rows:
        if r.get("skipped"):
            continue
        if r.get("had_error"):
            continue
        result = r.get("result")
        if result not in (WIN, LOSS, DRAW):
            continue
        t1, t2 = r["trainer1"], r["trainer2"]
        stats[t1]["battles"] += 1
        stats[t2]["battles"] += 1
        if result == WIN:
            stats[t1]["wins"] += 1
            stats[t2]["losses"] += 1
            fit_rows.append((t1, t2, 1))
        elif result == LOSS:
            stats[t2]["wins"] += 1
            stats[t1]["losses"] += 1
            fit_rows.append((t1, t2, 0))
        else:
            stats[t1]["draws"] += 1
            stats[t2]["draws"] += 1

    trainers = sorted(stats.keys())
    if not trainers or not fit_rows:
        return [], stats

    index = {name: i for i, name in enumerate(trainers)}
    n_trainers = len(trainers)
    n_battles = len(fit_rows)

    # One row per battle: +1 in trainer1's column, -1 in trainer2's column.
    row_idx = np.repeat(np.arange(n_battles), 2)
    col_idx = np.empty(n_battles * 2, dtype=np.int64)
    data = np.empty(n_battles * 2, dtype=np.float64)
    y = np.empty(n_battles, dtype=np.int64)
    for i, (t1, t2, target) in enumerate(fit_rows):
        col_idx[2 * i] = index[t1]
        data[2 * i] = 1.0
        col_idx[2 * i + 1] = index[t2]
        data[2 * i + 1] = -1.0
        y[i] = target

    X = coo_matrix((data, (row_idx, col_idx)), shape=(n_battles, n_trainers)).tocsr()

    model = LogisticRegression(fit_intercept=False, max_iter=1000)
    model.fit(X, y)
    coefs = model.coef_[0]

    leaderboard = []
    for name, idx in index.items():
        s = stats[name]
        leaderboard.append({
            "trainer": name,
            "rating": round(coefs[idx] * ELO_SCALE + ELO_BASE, 2),
            "wins": s["wins"],
            "losses": s["losses"],
            "draws": s["draws"],
            "battles": s["battles"],
        })
    leaderboard.sort(key=lambda row: row["rating"], reverse=True)
    for rank, row in enumerate(leaderboard, start=1):
        row["rank"] = rank

    return leaderboard, stats


def write_outputs(fmt, leaderboard):
    json_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}.json")
    csv_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "trainer", "rating", "wins", "losses", "draws", "battles"])
        writer.writeheader()
        writer.writerows(leaderboard)

    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", help="Only compute this format (default: all formats found in results/)")
    args = parser.parse_args()

    formats = [args.format] if args.format else discover_formats()
    if not formats:
        print("No elo_results_*_shard*.jsonl files found under results/.")
        return

    for fmt in formats:
        leaderboard, stats = compute_ratings(fmt)
        if not leaderboard:
            print(f"[{fmt}] No usable (non-skipped, win/loss/draw) results yet -- skipping.")
            continue
        json_path, csv_path = write_outputs(fmt, leaderboard)
        total_battles = sum(s["battles"] for s in stats.values()) // 2
        print(f"[{fmt}] {len(leaderboard)} trainers, {total_battles} battles -> {csv_path}")
        print(f"[{fmt}] Top 5: " + ", ".join(f"{row['trainer']} ({row['rating']})" for row in leaderboard[:5]))


if __name__ == "__main__":
    main()
