#!/usr/bin/env python3
"""
Winrate + best-win/worst-loss report for a custom trainer's battles against
the pool, produced by scripts/run_custom_trainer.ps1 (which writes
shards/shard<N>/Analysis/custom_trainer_results.jsonl per shard).

Same definitions as best_worst.py, applied to a single trainer who isn't
part of the rated pool: best_win is the highest-rated opponent the custom
trainer beat (most notable win), worst_loss is the lowest-rated opponent
that beat the custom trainer (most notable/unexpected loss). Opponent
skill comes from the *existing* ratings_<format>.json (or
ratings_<format>_cursed_excluded.json with --exclude-cursed) -- this script
doesn't rate the custom trainer itself, just ranks its results against
where its opponents already sit.

Prints the save_replay.ps1 command for each of best_win/worst_loss so the
two fights worth watching can be re-recorded while the run's seeds are
still on hand.
"""
import argparse
import glob
import json
import os

import results_lib
from results_lib import ANALYSIS_DIR, REPO_ROOT

WIN, LOSS, DRAW = results_lib.WIN, results_lib.LOSS, results_lib.DRAW


def load_custom_results(results_dir, fmt):
    rows = []
    for path in sorted(glob.glob(os.path.join(results_dir, f"custom_trainer_results_{fmt}_shard*.jsonl"))):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"  (skipped an unparseable line in {path})")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", default="singles", help="Battle format the custom trainer fought in (default: singles)")
    parser.add_argument("--exclude-cursed", action="store_true", help="Rank opponents by ratings_<format>_cursed_excluded.json instead of ratings_<format>.json")
    parser.add_argument("--results-dir", default=os.path.join(REPO_ROOT, "results"), metavar="DIR", help="Directory containing custom_trainer_results_<format>_shard*.jsonl (default: results/)")
    parser.add_argument("--pbs-file", help="Path to the custom trainer's PBS snippet, printed into the suggested save_replay.ps1 commands (-CustomTrainerPbs)")
    args = parser.parse_args()

    rows = load_custom_results(args.results_dir, args.format)
    if not rows:
        print(f"No custom_trainer_results_{args.format}_shard*.jsonl rows found under {args.results_dir}. Run scripts/run_custom_trainer.ps1 first.")
        return

    error_rows = [r for r in rows if "result" not in r]
    for r in error_rows:
        print(f"  (error row, skipped: {r.get('error_class')}: {r.get('error_message')})")
    rows = [r for r in rows if "result" in r]
    if not rows:
        print("No successful battles to report on.")
        return

    custom_label = rows[0]["custom"]
    fmt = rows[0]["format"]

    suffix = "_cursed_excluded" if args.exclude_cursed else ""
    ratings_by_label = results_lib.load_ratings(args.format, suffix, analysis_dir=ANALYSIS_DIR)

    wins = sum(1 for r in rows if r["result"] == WIN)
    losses = sum(1 for r in rows if r["result"] == LOSS)
    draws = sum(1 for r in rows if r["result"] == DRAW)
    had_error_count = sum(1 for r in rows if r.get("had_error"))

    best_win = None    # (opponent_rating, opponent_label, seed)
    worst_loss = None
    for r in rows:
        opponent = r["opponent"]
        rating = ratings_by_label.get(opponent, {}).get("rating")
        if rating is None:
            continue
        if r["result"] == WIN:
            if best_win is None or rating > best_win[0]:
                best_win = (rating, opponent, r["seed"])
        elif r["result"] == LOSS:
            if worst_loss is None or rating < worst_loss[0]:
                worst_loss = (rating, opponent, r["seed"])

    total = wins + losses + draws
    winrate = wins / total if total else 0.0

    print(f"Custom trainer: {custom_label}  ({fmt}{suffix})")
    print(f"Battles: {total}  (W {wins} / L {losses} / D {draws}), had_error: {had_error_count}, error rows: {len(error_rows)}")
    print(f"Winrate: {winrate:.1%}")

    def describe(entry, label):
        if entry is None:
            print(f"{label}: none")
            return None
        rating, opponent, seed = entry
        print(f"{label}: vs {opponent} (rating {rating:.1f}), seed {seed}")
        pbs_arg = f" -CustomTrainerPbs \"{args.pbs_file}\"" if args.pbs_file else " -CustomTrainerPbs \"<path to your custom trainer PBS snippet>\""
        print(f"  .\\scripts\\save_replay.ps1 -Trainer1 \"{custom_label}\" -Trainer2 \"{opponent}\" -Seed {seed} -Format {args.format}{pbs_arg}")
        return {"opponent": opponent, "rating": rating, "seed": seed}

    best_win_json = describe(best_win, "Best win")
    worst_loss_json = describe(worst_loss, "Worst loss")

    out = {
        "custom_trainer": custom_label,
        "format": fmt,
        "ranked_against": f"ratings_{args.format}{suffix}.json",
        "battles": total,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "winrate": winrate,
        "best_win": best_win_json,
        "worst_loss": worst_loss_json,
    }
    out_path = os.path.join(ANALYSIS_DIR, f"custom_trainer_report_{args.format}{suffix}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
