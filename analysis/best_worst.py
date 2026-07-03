#!/usr/bin/env python3
"""
Per-trainer best win / worst loss, cached to analysis/best_worst_<format>.json.

Reads every results/remote/elo_results_<format>_shard*.jsonl (default; use
--results-dir results/ for local shard data) and that format's own
ratings_<format>.json (from ratings.py), and for every trainer records the
highest-rated opponent they beat (best_win) and the lowest-rated opponent
they lost to (worst_loss), each with the seed of that battle (for
ELO_SAVE_REPLAY). Either field is null if the trainer has no such result
(e.g. undefeated, or no wins at all).

trainer_cards.py used to compute this itself by rescanning every shard file
once per trainer it rendered -- fine for a single --trainer render, but
wasteful for --test-cases (rescans the whole result set once per test case)
and would be O(trainers^2) for a hypothetical "render every trainer" mode.
This does one pass over the results for the whole format instead, so
trainer_cards.py (or any other future consumer) just looks its trainer up
in the cache.

Run this after ratings.py for a given format; re-run it whenever the
underlying results change, same as ratings.py.

--exclude-cursed mirrors ratings.py's own flag of the same name: pass the
base format (e.g. "doubles") plus --exclude-cursed, not "doubles_cursed_excluded"
as --format, to produce best_worst_doubles_cursed_excluded.json from
ratings_doubles_cursed_excluded.json.
"""
import argparse
import json
import os

import results_lib
from results_lib import ANALYSIS_DIR, REPO_ROOT

RESULTS_DIR = results_lib.RESULTS_DIR

WIN, LOSS = 1, 2


def compute_best_worst(fmt, ratings_by_label, exclude_cursed=False):
    """One pass over every battle in the format: for each trainer, the
    highest-rated opponent beaten (best_win) and lowest-rated opponent lost
    to (worst_loss), each as (opponent_rating, opponent_label, seed).

    exclude_cursed mirrors ratings.py's --exclude-cursed: there's no separate
    elo_results_<fmt>_cursed_excluded_shard*.jsonl on disk (ratings.py's
    "cursed_excluded" leaderboard is just the normal <fmt> results with
    curse-flagged battles -- plus the ASYMMETRIC_CURSE_PAIRS special case,
    see results_lib -- filtered out, saved under a _cursed_excluded-suffixed
    filename), so this must filter the same way rather than globbing for a
    results file that will never exist."""
    best_win = {}
    worst_loss = {}
    for row in results_lib.load_results(fmt, results_dir=RESULTS_DIR):
        if row.get("skipped") or row.get("had_error"):
            continue
        if exclude_cursed and results_lib.is_cursed_excluded(row):
            continue
        t1, t2, result = row.get("trainer1"), row.get("trainer2"), row.get("result")
        if result not in (WIN, LOSS):
            continue
        seed = row.get("seed")
        winner, loser = (t1, t2) if result == WIN else (t2, t1)
        loser_rating = ratings_by_label.get(loser, {}).get("rating")
        if loser_rating is not None:
            cur = best_win.get(winner)
            if cur is None or loser_rating > cur[0]:
                best_win[winner] = (loser_rating, loser, seed)
        winner_rating = ratings_by_label.get(winner, {}).get("rating")
        if winner_rating is not None:
            cur = worst_loss.get(loser)
            if cur is None or winner_rating < cur[0]:
                worst_loss[loser] = (winner_rating, winner, seed)
    return best_win, worst_loss


def to_json_entry(entry):
    if entry is None:
        return None
    rating, opponent, seed = entry
    return {"opponent": opponent, "rating": rating, "seed": seed}


def write_output(fmt, suffix, best_win, worst_loss, trainers):
    out = {
        label: {
            "best_win": to_json_entry(best_win.get(label)),
            "worst_loss": to_json_entry(worst_loss.get(label)),
        }
        for label in trainers
    }
    path = os.path.join(ANALYSIS_DIR, f"best_worst_{fmt}{suffix}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return path


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", help="Only compute this format (default: all formats found in --results-dir)")
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    parser.add_argument(
        "--exclude-cursed", action="store_true",
        help=(
            "Drop every battle flagged curse (plus results_lib.ASYMMETRIC_CURSE_PAIRS's extra "
            "half), matching `ratings.py --exclude-cursed`, and read/write the _cursed_excluded-suffixed "
            "files (ratings_<fmt>_cursed_excluded.json in, best_worst_<fmt>_cursed_excluded.json "
            "out) instead of the normal ones. --format should still name the base format (e.g. 'doubles', "
            "not 'doubles_cursed_excluded') -- there is no elo_results_<fmt>_cursed_excluded_shard*.jsonl on disk."
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
        ratings_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}{suffix}.json")
        if not os.path.exists(ratings_path):
            print(f"[{fmt}] {ratings_path} not found -- run ratings.py first. Skipping.")
            continue
        ratings_by_label = results_lib.load_ratings(fmt, suffix, analysis_dir=ANALYSIS_DIR)
        best_win, worst_loss = compute_best_worst(fmt, ratings_by_label, exclude_cursed=args.exclude_cursed)
        path = write_output(fmt, suffix, best_win, worst_loss, ratings_by_label.keys())
        print(f"[{fmt}{suffix}] {len(ratings_by_label)} trainers -> {path}")


if __name__ == "__main__":
    main()
