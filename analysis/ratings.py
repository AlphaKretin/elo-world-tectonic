#!/usr/bin/env python3
"""
Bradley-Terry trainer ratings from ELO Tournament battle results.

Reads every results/current/elo_results_<format>_shard*.jsonl (default;
use --results-dir results/local/ or results/remote/ for not-yet-promoted
data), fits one-hot ±1 logistic regression per format (Bradley-Terry), and
writes a sorted leaderboard (CSV + JSON) per format to analysis/ratings/.

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

--filter NAME (repeatable) applies one of results_lib.FILTERS' named
row-level "keep this battle" predicates before fitting, and writes a
parallel ratings_<fmt>_<name1>_<name2>...json/csv leaderboard (names joined
in results_lib.FILTERS' own order, so a single filter's suffix matches its
name exactly, e.g. --filter cursed_excluded -> _cursed_excluded).

--filter cursed_excluded drops every battle flagged curse (tournament.rb
tags a battle curse if either trainer had a CURSE_* policy active in it),
to see how the field shakes out without curse-skewed results pulling on
the fit. Cursed trainers' curses are active in every battle they play, so
they end up with no data and don't appear in the cursed_excluded
leaderboard at all -- same for the two known trainers whose curse is
authored on their duo partner's side instead of their own (see
results_lib.ASYMMETRIC_CURSE_PAIRS).

This is a blunt, post-hoc data filter, not a simulation of what cursed
trainers "should" look like -- for that, see the singles_uncursed/
doubles_uncursed formats (results_lib.load_results merges the raw
curse-stripped re-battles in memory with the base results on every load --
see results_lib.is_uncursed_format), which re-battle cursed trainers with
curse *effects* actually stripped instead of just discarding their data.

--filter level70_only keeps only battles where both trainers have exactly
6 Pokemon at level 70 -- the endgame/developer-team cohort, whose battles
against underleveled trainers otherwise inflate their rating without
saying much about how they'd fare against actual peers.

--filter developer_only keeps only battles where both trainers carry the
TrainerTypeLabel = DEVELOPER display override (a label swap, not a real
TrainerType -- see results_lib.is_developer_trainer) -- a "these are
actual people" cohort that overlaps heavily with level70_only but isn't
identical to it.

Filters are composable (e.g. --filter cursed_excluded --filter
level70_only); each additional filter only narrows the fit further.

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

import results_lib
from results_lib import REPO_ROOT, WIN, LOSS, DRAW

RESULTS_DIR = results_lib.RESULTS_DIR

# rating = coefficient * ELO_SCALE + ELO_BASE, the standard logistic-regression
# Elo conversion (173 ~= 400 / ln(10), matching the usual Elo logistic curve).
ELO_SCALE = 173
ELO_BASE = 1500

# The fit minimizes 0.5*||w - w0||^2 + C * log_loss(w) -- the L2 term is a
# Gaussian prior (mean w0, default 0) on each coefficient, not an
# afterthought -- it's also what makes the fit well-posed at all: a plain
# Bradley-Terry design (each row is +1/-1 in two trainer columns, no
# intercept) is only identifiable up to an additive constant (shifting every
# rating by the same amount changes no prediction), so the unpenalized
# Fisher information X^T W X is singular. The penalty's curvature (the +1
# along the diagonal in fit_bt) resolves that the same way it resolves the
# point estimate, so REG_C has to be the same value the model itself is fit
# with.
REG_C = 1.0
CI_Z = 1.96  # ~95% normal-approximation interval


def _design_matrix(fit_rows, index):
    """+1/-1 one-hot battle design matrix: row i is +1 in fit_rows[i][0]'s
    column, -1 in fit_rows[i][1]'s column. Shared by every fit below."""
    n_trainers = len(index)
    n_battles = len(fit_rows)
    row_idx = np.repeat(np.arange(n_battles), 2)
    col_idx = np.empty(n_battles * 2, dtype=np.int64)
    data = np.empty(n_battles * 2, dtype=np.float64)
    y = np.empty(n_battles, dtype=np.float64)
    for i, (t1, t2, target) in enumerate(fit_rows):
        col_idx[2 * i] = index[t1]
        data[2 * i] = 1.0
        col_idx[2 * i + 1] = index[t2]
        data[2 * i + 1] = -1.0
        y[i] = target
    X = coo_matrix((data, (row_idx, col_idx)), shape=(n_battles, n_trainers)).tocsr()
    return X, y


def fit_bt(fit_rows, index, w0=None, C=REG_C, max_iter=100, tol=1e-9):
    """Penalized Newton-Raphson (IRLS/Fisher scoring) fit of
    C*log_loss(w) + 0.5*||w - w0||^2 -- the standard MLE update for a
    ridge-penalized (Gaussian-prior) logistic regression, generalized to an
    arbitrary prior mean w0 (default 0) so a curse-stripped format's fit
    can be anchored to its base format's shared-battle ratings instead of
    to zero (see compute_anchored_uncursed_pair). Textbook method -- same
    Fisher-scoring update used to derive ridge logistic regression in any
    standard GLM reference (e.g. McCullagh & Nelder, "Generalized Linear
    Models"), and the same IRLS iteration statsmodels.GLM.fit() uses
    internally for its unpenalized case.

    Hand-rolled rather than an off-the-shelf package because neither
    option actually reaches the true optimum on this problem's scale
    (verified 2026-07-08): sklearn's LogisticRegression has no way to
    penalize toward a nonzero w0 at all (only ever toward zero), and its
    default tolerance silently under-converges even the zero-mean case for
    a ~555-trainer/~150k-battle fit (5 lbfgs iterations, ~400+ rating
    points of error concentrated in the most lopsided win/loss records --
    the likelihood surface is very flat in those directions, so a small
    gradient norm doesn't mean the coefficient itself is near-converged).
    statsmodels.GLM.fit_regularized *does* support an offset + L2 penalty
    together, which is closer to what's needed here, but its elastic-net
    solver still left up to 31 rating points of residual error on the full
    fit even at tightened tolerance/maxiter, and took ~2x longer than this
    solver besides.

    This solver converges quadratically once near the optimum (step size
    2.0 -> 1e-14 in 8 iterations on the full singles fit) because the
    objective is strictly convex (the L2 term guarantees a unique,
    Hessian-positive-definite optimum -- no local-optimum ambiguity to
    worry about). Matches a tightly-converged sklearn fit (the one config
    an established package can serve as ground truth for -- w0=0, no
    offset) to 0.0005 rating points; see verify_bt_fit.py for the pinned
    regression check."""
    n = len(index)
    if w0 is None:
        w0 = np.zeros(n)
    X, y = _design_matrix(fit_rows, index)
    X_dense = X.toarray()
    w = w0.copy()
    hessian = np.eye(n)
    for _ in range(max_iter):
        margins = X_dense @ w
        p = 1.0 / (1.0 + np.exp(-margins))
        grad = C * X_dense.T @ (p - y) + (w - w0)
        wts = p * (1 - p)
        hessian = np.eye(n) + C * (X_dense * wts[:, None]).T @ X_dense
        step = np.linalg.solve(hessian, grad)
        w = w - step
        if np.max(np.abs(step)) < tol:
            break
    return w, hessian


def _collect_stats_and_fit_rows(rows, filters, trainer_data, exclude_trainers):
    """Shared row-walking loop: per-trainer win/loss/draw/battle stats plus
    the (trainer1, trainer2, target) list fit_bt needs. Draws count toward
    stats but are excluded from the fit itself -- plain Bradley-Terry
    models a binary win/loss outcome."""
    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "draws": 0, "battles": 0})
    fit_rows = []
    for r in rows:
        if r.get("skipped") or r.get("had_error"):
            continue
        if not results_lib.passes_filters(r, filters, trainer_data):
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
    return stats, fit_rows


def _build_leaderboard(index, stats, coefs, hessian):
    """Turns a fit's coefficients + Hessian into the public leaderboard
    shape (rating/se/ci/wins/losses/draws/battles/rank/overlap/tier).
    `index` may be a subset of the trainers `coefs`/`hessian` were fit
    over (see compute_anchored_uncursed_pair, where cursed and uncursed
    leaderboards each cover a different trainer subset of one shared fit)
    -- values in `index` are still valid positions into the full arrays."""
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
    return leaderboard


def compute_ratings(fmt, exclude_trainers=(), filters=()):
    rows = results_lib.load_results(fmt, results_dir=RESULTS_DIR, report_skipped=True)
    trainer_data = results_lib.load_trainer_data_if_needed(filters)
    stats, fit_rows = _collect_stats_and_fit_rows(rows, filters, trainer_data, exclude_trainers)

    trainers = sorted(stats.keys())
    if not trainers or not fit_rows:
        return [], stats

    index = {name: i for i, name in enumerate(trainers)}
    coefs, hessian = fit_bt(fit_rows, index)
    leaderboard = _build_leaderboard(index, stats, coefs, hessian)
    return leaderboard, stats


def compute_anchored_uncursed_pair(base_fmt, exclude_trainers=(), filters=()):
    """Fits base_fmt and base_fmt+'_uncursed' together, anchored to a
    shared reference point instead of each independently to zero.

    compare_formats.py's rating_delta was dropped because two
    independently zero-anchored Bradley-Terry fits have no shared
    reference -- each format's "zero point" is wherever that population's
    own regularized optimum happened to settle, so a raw subtraction isn't
    a real quantity (confirmed empirically: even trainers with provably
    unchanged battle outcomes drifted a few points purely from everyone
    else's refit). Singles vs. doubles has no fix for this -- they share
    no battles at all. Cursed vs. uncursed is different: the large
    majority of battles are *literally identical* rows in both formats
    (every curse:false pairing, plus every curse:true pairing where
    stripping the curse turned out to be a no-op -- see
    results_lib._merge_uncursed). Only the pairings where a curse actually
    changed a party get re-battled. That shared population gives the two
    formats a real common reference point:

      1. Fit a zero-anchored model on ONLY the shared/identical battles --
         one rating per trainer, common to both formats by construction.
      2. Fit each format's own model on its FULL battle set (shared rows +
         that format's own differing rows), regularized toward step 1's
         ratings instead of toward zero.
      3. uncursed_rating - cursed_rating is now a trainer's estimated
         strength shift specifically attributable to curse removal
         (propagated through the shared battle graph), not an artifact of
         two unrelated fits landing in different neighborhoods.

    Validated 2026-07-08 on singles (full roster) and doubles+level70_only
    (a much smaller, differently-shaped stress test): |delta|/SE lands in
    the same sane range for both (median ~1.1-1.2 SE, ~15-20% exceeding 2
    SE as plausibly-real movement), not a blowup or degenerate collapse.

    This changes the standalone per-format ratings too (regularization now
    pulls toward the shared baseline, not zero) -- a deliberate tradeoff
    for a meaningful comparison, not a bug.

    Returns (base_leaderboard, uncursed_leaderboard, base_stats,
    uncursed_stats), or None if there are no shared battles to anchor on
    (caller should fall back to two independent compute_ratings calls)."""
    uncursed_fmt = base_fmt + results_lib.UNCURSED_SUFFIX
    base_rows = results_lib.load_results(base_fmt, results_dir=RESULTS_DIR, report_skipped=True)
    uncursed_rows = results_lib.load_results(uncursed_fmt, results_dir=RESULTS_DIR, report_skipped=True)
    raw_rows = results_lib.load_shard_files(uncursed_fmt, RESULTS_DIR)

    trainer_data = results_lib.load_trainer_data_if_needed(filters)
    if filters:
        base_rows = [r for r in base_rows if results_lib.passes_filters(r, filters, trainer_data)]
        uncursed_rows = [r for r in uncursed_rows if results_lib.passes_filters(r, filters, trainer_data)]
        raw_rows = [r for r in raw_rows if results_lib.passes_filters(r, filters, trainer_data)]

    raw_pairs = {results_lib.pair_key(r) for r in raw_rows}
    uncursed_pairs = {results_lib.pair_key(r) for r in uncursed_rows}

    shared_rows, cursed_only_rows, dropped_rows = [], [], []
    for row in base_rows:
        pk = results_lib.pair_key(row)
        if pk in raw_pairs:
            cursed_only_rows.append(row)  # superseded -- replaced by a fresh curse-stripped battle
        elif pk in uncursed_pairs:
            shared_rows.append(row)  # identical in both formats
        else:
            dropped_rows.append(row)  # identical_to_base exclusion -- absent from uncursed entirely

    if not shared_rows:
        return None

    trainers = sorted(
        {r["trainer1"] for r in base_rows} | {r["trainer2"] for r in base_rows}
        | {r["trainer1"] for r in uncursed_rows} | {r["trainer2"] for r in uncursed_rows}
    )
    index = {t: i for i, t in enumerate(trainers)}

    _, anchor_fit_rows = _collect_stats_and_fit_rows(shared_rows, (), None, exclude_trainers)
    anchor_w, _ = fit_bt(anchor_fit_rows, index)

    cursed_stats, cursed_fit_rows = _collect_stats_and_fit_rows(
        shared_rows + cursed_only_rows + dropped_rows, (), None, exclude_trainers)
    uncursed_stats, uncursed_fit_rows = _collect_stats_and_fit_rows(
        shared_rows + raw_rows, (), None, exclude_trainers)

    cursed_w, cursed_h = fit_bt(cursed_fit_rows, index, w0=anchor_w)
    uncursed_w, uncursed_h = fit_bt(uncursed_fit_rows, index, w0=anchor_w)

    cursed_index = {t: index[t] for t in cursed_stats}
    uncursed_index = {t: index[t] for t in uncursed_stats}

    base_leaderboard = _build_leaderboard(cursed_index, cursed_stats, cursed_w, cursed_h)
    uncursed_leaderboard = _build_leaderboard(uncursed_index, uncursed_stats, uncursed_w, uncursed_h)
    return base_leaderboard, uncursed_leaderboard, cursed_stats, uncursed_stats


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
    os.makedirs(results_lib.RATINGS_DIR, exist_ok=True)
    json_path = os.path.join(results_lib.RATINGS_DIR, f"ratings_{fmt}{suffix}.json")
    csv_path = os.path.join(results_lib.RATINGS_DIR, f"ratings_{fmt}{suffix}.csv")

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
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/current/; use results/local/ or results/remote/ for not-yet-promoted data)",
    )
    parser.add_argument(
        "--exclude-trainer", action="append", default=[], metavar="LABEL",
        help="Trainer label (e.g. 'ROLLERSKATER_F:Attea') to drop from the fit entirely. Repeatable.",
    )
    parser.add_argument(
        "--anchor-uncursed", action="store_true",
        help="Treat --format as a base format (e.g. 'singles') and fit it together with its "
             "'<format>_uncursed' counterpart, anchored to their shared battles instead of each "
             "independently to zero -- see compute_anchored_uncursed_pair. Writes both formats.",
    )
    results_lib.add_filter_arg(parser)
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    suffix = results_lib.filter_suffix(args.filter)

    if args.anchor_uncursed:
        if not args.format:
            raise SystemExit("--anchor-uncursed requires --format <base format, e.g. singles>")
        pair = compute_anchored_uncursed_pair(
            args.format, exclude_trainers=set(args.exclude_trainer), filters=args.filter,
        )
        if pair is None:
            print(f"[{args.format}] No shared battles with its uncursed counterpart -- nothing to anchor.")
            return
        base_leaderboard, uncursed_leaderboard, base_stats, uncursed_stats = pair
        for fmt, leaderboard, stats in (
            (args.format, base_leaderboard, base_stats),
            (args.format + results_lib.UNCURSED_SUFFIX, uncursed_leaderboard, uncursed_stats),
        ):
            json_path, csv_path = write_outputs(fmt, leaderboard, suffix=suffix)
            total_battles = sum(s["battles"] for s in stats.values()) // 2
            print(f"[{fmt}] {len(leaderboard)} trainers, {total_battles} battles -> {csv_path}")
            print(f"[{fmt}] Top 5: " + ", ".join(f"{row['trainer']} ({row['rating']}, {row['tier']})" for row in leaderboard[:5]))
        return

    formats = [args.format] if args.format else results_lib.discover_formats(RESULTS_DIR)
    if not formats:
        print(f"No elo_results_*_shard*.jsonl files found under {RESULTS_DIR}.")
        return

    for fmt in formats:
        leaderboard, stats = compute_ratings(
            fmt, exclude_trainers=set(args.exclude_trainer), filters=args.filter,
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
