#!/usr/bin/env python3
"""
Bradley-Terry trainer ratings from ELO Tournament battle results.

Reads every results/remote/elo_results_<format>_shard*.jsonl (default;
use --results-dir results/ for local shard data), fits one-hot
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
writes a parallel ratings_<fmt>_cursed_excluded.json/csv leaderboard, to see
how the field shakes out without curse-skewed results pulling on the fit.
Cursed trainers' curses are active in every battle they play, so they end
up with no data and don't appear in the cursed_excluded leaderboard at all
-- same for the two known trainers whose curse is authored on their duo
partner's side instead of their own (see results_lib.ASYMMETRIC_CURSE_PAIRS).

This is a blunt, post-hoc data filter, not a simulation of what cursed
trainers "should" look like -- for that, see the singles_uncursed/
doubles_uncursed formats (built by build_uncursed_results.py from the raw
curse-stripped re-battles plus the base results), which re-battle cursed
trainers with curse *effects* actually stripped instead of just discarding
their data.

Each trainer's rating also gets a standard error and a 95% confidence
interval, plus an "overlap" count -- how many *other* trainers' point
ratings fall inside this trainer's own CI. At ~30 games/trainer, a
trainer with a lopsided record against whatever they were randomly
matched against isn't necessarily precisely ranked -- the overlap count
makes that visible instead of leaving rank to imply more precision than
the data actually supports.

Each row also gets a 15-tier S-F tier (in the elo_world_pokemon_red/
crystal style: F, D-/D/D+, C-/C/C+, B-/B/B+, A-/A/A+, S/S+) via two-stage
k-means -- not the hand-picked fixed Elo breakpoints upstream actually
shipped (those would need re-picking by hand every time this dataset's
scale changes), and not flat 15-cluster k-means either, since a single
pass has no notion that e.g. C+ should stay closer to C than to B-. See
assign_tiers for the two-stage approach that fixes that.
"""
import argparse
import csv
import json
import os
from collections import defaultdict

import numpy as np
from scipy.sparse import coo_matrix
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression

import results_lib
from results_lib import ANALYSIS_DIR, REPO_ROOT, WIN, LOSS, DRAW

RESULTS_DIR = results_lib.RESULTS_DIR

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


def compute_ratings(fmt, exclude_trainers=(), exclude_cursed=False):
    rows = results_lib.load_results(fmt, results_dir=RESULTS_DIR, report_skipped=True)

    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "draws": 0, "battles": 0})
    fit_rows = []  # (trainer1, trainer2, target) for the regression

    for r in rows:
        if r.get("skipped"):
            continue
        if r.get("had_error"):
            continue
        if exclude_cursed and results_lib.is_cursed_excluded(r):
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

    assign_tiers(leaderboard)

    return leaderboard, stats


# Bottom to top; F has no +/- (a single tier), S has no "-" (just S/S+) --
# matching elo_world_pokemon_red's own 15-name list exactly.
TIER_MACRO_LETTERS = ["F", "D", "C", "B", "A", "S"]
TIER_SUFFIXES = {
    "F": [""],
    "D": ["-", "", "+"],
    "C": ["-", "", "+"],
    "B": ["-", "", "+"],
    "A": ["-", "", "+"],
    "S": ["", "+"],
}


def assign_tiers(leaderboard):
    """Two-stage k-means: a macro pass (K=6) sorted by cluster center into
    F/D/C/B/A/S, then a second pass *within* each macro group's own
    members for the +/- split. Two-stage rather than one flat K=15 pass so
    a C+ trainer is guaranteed to be a member of the same macro cluster as
    C/C-, not just whichever of 15 raw clusters happens to land nearby --
    a flat pass has no notion that C+ should stay closer to C than to B-.
    Mutates leaderboard in place, adding a "tier" field to every row (None
    if there aren't even enough trainers for one per macro tier)."""
    if len(leaderboard) < len(TIER_MACRO_LETTERS):
        for row in leaderboard:
            row["tier"] = None
        return

    ratings_arr = np.array([row["rating"] for row in leaderboard]).reshape(-1, 1)
    macro_km = KMeans(n_clusters=len(TIER_MACRO_LETTERS), n_init=10, random_state=0).fit(ratings_arr)
    macro_order = np.argsort(macro_km.cluster_centers_.ravel())
    macro_letter = {cluster: TIER_MACRO_LETTERS[rank] for rank, cluster in enumerate(macro_order)}
    macro_tiers = [macro_letter[cluster] for cluster in macro_km.labels_]

    for letter, suffixes in TIER_SUFFIXES.items():
        group = [row for row, tier in zip(leaderboard, macro_tiers) if tier == letter]
        if len(suffixes) == 1 or len(group) < len(suffixes):
            for row in group:
                row["tier"] = letter
            continue
        group_ratings = np.array([row["rating"] for row in group]).reshape(-1, 1)
        sub_km = KMeans(n_clusters=len(suffixes), n_init=10, random_state=0).fit(group_ratings)
        sub_order = np.argsort(sub_km.cluster_centers_.ravel())
        suffix_by_cluster = {cluster: suffixes[rank] for rank, cluster in enumerate(sub_order)}
        for row, cluster in zip(group, sub_km.labels_):
            row["tier"] = letter + suffix_by_cluster[cluster]


def write_outputs(fmt, leaderboard, suffix=""):
    json_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}{suffix}.json")
    csv_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}{suffix}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "rank", "trainer", "rating", "tier", "se", "ci_low", "ci_high", "overlap",
            "wins", "losses", "draws", "battles",
        ])
        writer.writeheader()
        writer.writerows(leaderboard)

    return json_path, csv_path


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", help="Only compute this format (default: all formats found in --results-dir)")
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    parser.add_argument(
        "--exclude-trainer", action="append", default=[], metavar="LABEL",
        help="Trainer label (e.g. 'ROLLERSKATER_F:Attea') to drop from the fit entirely. Repeatable.",
    )
    parser.add_argument(
        "--exclude-cursed", action="store_true",
        help=(
            "Drop every battle flagged curse (either side had a CURSE_* policy active), plus battles "
            "involving the non-curse-flagged half of a known asymmetric CURSE_NO_MERCY pair (see "
            "results_lib.ASYMMETRIC_CURSE_PAIRS), from the fit, and write to "
            "ratings_<fmt>_cursed_excluded.json/csv instead of the normal output. Since a cursed "
            "trainer's curse is active in every battle it plays (see tournament.rb's pairsForEdge), "
            "this leaves cursed trainers with no data and they won't appear in the result."
        ),
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    formats = [args.format] if args.format else results_lib.discover_formats(RESULTS_DIR)
    if not formats:
        print(f"No elo_results_*_shard*.jsonl files found under {RESULTS_DIR}.")
        return

    suffix = "_cursed_excluded" if args.exclude_cursed else ""
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
        print(f"[{fmt}] Top 5: " + ", ".join(f"{row['trainer']} ({row['rating']}, {row['tier']})" for row in leaderboard[:5]))


if __name__ == "__main__":
    main()
