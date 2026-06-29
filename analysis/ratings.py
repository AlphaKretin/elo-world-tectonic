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

--exclude-trainer drops a trainer (by its "TYPE:Name" or "TYPE:Name#N"
label) from the fit entirely, e.g. for ROLLERSKATER_F:Attea, whose
ALLOW_RANDOM_MOVES policy is too chaotic to be meaningful rating data --
see trainer_pool.rb's QUARANTINED_POLICIES comment for why that isn't
filtered at the trainer-pool level instead.

--exclude-cursed drops every battle flagged curse (tournament.rb tags a
battle curse if either trainer had a CURSE_* policy active in it) and
writes a parallel ratings_<fmt>_uncursed.json/csv leaderboard, to see how
the field shakes out without curse-skewed results pulling on the fit.
Cursed trainers' curses are active in every battle they play, so they end
up with no data and don't appear in the uncursed leaderboard at all.

Each trainer's rating also gets a standard error and a 95% confidence
interval, plus an "overlap" count -- how many *other* trainers' point
ratings fall inside this trainer's own CI. At ~30 games/trainer, a
trainer with a lopsided record against whatever they were randomly
matched against isn't necessarily precisely ranked -- the overlap count
makes that visible instead of leaving rank to imply more precision than
the data actually supports.
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

# sklearn's LogisticRegression(C=REG_C) minimizes 0.5*||w||^2 + C * log_loss,
# so the L2 term is a unit-Gaussian prior on each coefficient, not an
# afterthought -- it's also what makes the fit well-posed at all: a plain
# Bradley-Terry design (each row is +1/-1 in two trainer columns, no
# intercept) is only identifiable up to an additive constant (shifting every
# rating by the same amount changes no prediction), so the unpenalized
# Fisher information X^T W X is singular. The penalty's curvature (the +1
# along the diagonal below) resolves that the same way it resolves the point
# estimate, so REG_C has to be the same value the model itself is fit with.
REG_C = 1.0
CI_Z = 1.96  # ~95% normal-approximation interval


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


def compute_ratings(fmt, exclude_trainers=(), exclude_cursed=False):
    rows = load_results(fmt)

    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "draws": 0, "battles": 0})
    fit_rows = []  # (trainer1, trainer2, target) for the regression

    for r in rows:
        if r.get("skipped"):
            continue
        if r.get("had_error"):
            continue
        if exclude_cursed and r.get("curse"):
            continue
        result = r.get("result")
        if result not in (WIN, LOSS, DRAW):
            continue
        t1, t2 = r["trainer1"], r["trainer2"]
        if t1 in exclude_trainers or t2 in exclude_trainers:
            continue
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

    model = LogisticRegression(fit_intercept=False, C=REG_C, max_iter=1000)
    model.fit(X, y)
    coefs = model.coef_[0]

    # Laplace approximation: the inverse of the penalized fit's Hessian at
    # its own optimum approximates the coefficients' posterior covariance
    # (see REG_C's comment for why the penalty term has to match the fit).
    margins = X @ coefs
    p = 1.0 / (1.0 + np.exp(-margins))
    w = p * (1 - p)
    X_dense = X.toarray()
    hessian = np.eye(n_trainers) + REG_C * (X_dense * w[:, None]).T @ X_dense
    se_coef = np.sqrt(np.diag(np.linalg.inv(hessian)))
    se_rating = se_coef * ELO_SCALE

    leaderboard = []
    for name, idx in index.items():
        s = stats[name]
        rating = coefs[idx] * ELO_SCALE + ELO_BASE
        ci_half = CI_Z * se_rating[idx]
        leaderboard.append({
            "trainer": name,
            "rating": round(rating, 2),
            "se": round(se_rating[idx], 2),
            "ci_low": round(rating - ci_half, 2),
            "ci_high": round(rating + ci_half, 2),
            "wins": s["wins"],
            "losses": s["losses"],
            "draws": s["draws"],
            "battles": s["battles"],
        })
    leaderboard.sort(key=lambda row: row["rating"], reverse=True)
    for rank, row in enumerate(leaderboard, start=1):
        row["rank"] = rank

    # How many *other* trainers' point rating falls inside this trainer's
    # own CI -- a direct count of "statistically indistinguishable from me,"
    # rather than leaving that to be inferred from win/loss totals.
    ratings_arr = np.array([row["rating"] for row in leaderboard])
    for row in leaderboard:
        overlap = np.count_nonzero((ratings_arr >= row["ci_low"]) & (ratings_arr <= row["ci_high"]))
        row["overlap"] = int(overlap) - 1  # exclude self

    return leaderboard, stats


def write_outputs(fmt, leaderboard, suffix=""):
    json_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}{suffix}.json")
    csv_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}{suffix}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "rank", "trainer", "rating", "se", "ci_low", "ci_high", "overlap",
            "wins", "losses", "draws", "battles",
        ])
        writer.writeheader()
        writer.writerows(leaderboard)

    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", help="Only compute this format (default: all formats found in results/)")
    parser.add_argument(
        "--exclude-trainer", action="append", default=[], metavar="LABEL",
        help="Trainer label (e.g. 'ROLLERSKATER_F:Attea') to drop from the fit entirely. Repeatable.",
    )
    parser.add_argument(
        "--exclude-cursed", action="store_true",
        help=(
            "Drop every battle flagged curse (either side had a CURSE_* policy active) from the fit, "
            "and write to ratings_<fmt>_uncursed.json/csv instead of the normal output. Since a cursed "
            "trainer's curse is active in every battle it plays (see tournament.rb's pairsForEdge), "
            "this leaves cursed trainers with no data and they won't appear in the result."
        ),
    )
    args = parser.parse_args()

    formats = [args.format] if args.format else discover_formats()
    if not formats:
        print("No elo_results_*_shard*.jsonl files found under results/.")
        return

    suffix = "_uncursed" if args.exclude_cursed else ""
    for fmt in formats:
        leaderboard, stats = compute_ratings(
            fmt, exclude_trainers=set(args.exclude_trainer), exclude_cursed=args.exclude_cursed,
        )
        if not leaderboard:
            print(f"[{fmt}] No usable (non-skipped, win/loss/draw) results yet -- skipping.")
            continue
        json_path, csv_path = write_outputs(fmt, leaderboard, suffix=suffix)
        total_battles = sum(s["battles"] for s in stats.values()) // 2
        print(f"[{fmt}] {len(leaderboard)} trainers, {total_battles} battles -> {csv_path}")
        print(f"[{fmt}] Top 5: " + ", ".join(f"{row['trainer']} ({row['rating']})" for row in leaderboard[:5]))


if __name__ == "__main__":
    main()
