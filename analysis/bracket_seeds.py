#!/usr/bin/env python3
"""
Pulls the top 16 trainers out of analysis/ratings_<format>.json (run
ratings.py first) and writes results/bracket_seeds_<format>.txt -- the seed
list bracket.rb reads to set up the Round of 16.

Plain tab-separated text (seed, trainer label, rating) rather than JSON:
bracket.rb runs inside mkxp-z's embedded Ruby, which doesn't ship a JSON
parser (see tournament.rb's comment on the same constraint).
"""
import argparse
import json
import os

ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ANALYSIS_DIR)
RESULTS_DIR = os.path.join(REPO_ROOT, "results")

BRACKET_SIZE = 16


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", default="singles", help="Format to seed from (default: singles)")
    args = parser.parse_args()

    json_path = os.path.join(ANALYSIS_DIR, f"ratings_{args.format}.json")
    with open(json_path, "r", encoding="utf-8") as f:
        leaderboard = json.load(f)

    if len(leaderboard) < BRACKET_SIZE:
        raise SystemExit(f"Only {len(leaderboard)} rated trainers in {json_path}, need {BRACKET_SIZE}.")

    top = leaderboard[:BRACKET_SIZE]
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, f"bracket_seeds_{args.format}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        for seed, row in enumerate(top, start=1):
            f.write(f"{seed}\t{row['trainer']}\t{row['rating']}\n")

    print(f"Top {BRACKET_SIZE} seeds ({args.format}) -> {out_path}")
    for seed, row in enumerate(top, start=1):
        print(f"  {seed:2d}. {row['trainer']} ({row['rating']})")


if __name__ == "__main__":
    main()
