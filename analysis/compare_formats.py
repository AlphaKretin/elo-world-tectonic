#!/usr/bin/env python3
"""
Per-trainer rank/rating swing between two formats' leaderboards.

Reads analysis/ratings/ratings_<format>.json for two formats (default
singles vs doubles -- run ratings.py for both first) and, for every trainer
present in both, computes how far their *rank* moves between the two
leaderboards.

Rank is the only swing metric here, deliberately -- each format's
Bradley-Terry fit is `fit_intercept=False`, identified only by the L2
prior's pull toward zero (see ratings.py's REG_C comment), so there's no
shared anchor tying one format's zero-point to another's. A rating
*difference* is only meaningful within one fit's own battle graph, where
it has a real predicted-win-probability interpretation (rating = a base-10
Elo scale, see ratings.py's ELO_SCALE/ELO_BASE); across two independent
fits it's not measuring a real quantity, just wherever each population's
regularized optimum happened to settle. Confirmed empirically 2026-07-07:
after the resolutionChoice subset rerun, trainers whose actual battle
outcomes were provably unchanged (verified by diffing before/after
per-battle results) still showed small nonzero rating drift purely from
everyone else's refit -- the individual per-format ratings are still
shown as reference (each is meaningful in isolation), the delta between
them is not.

Ranks are rescaled to the intersection of the two formats' participants
before comparing -- trainers only ranked in one format (e.g. ineligible for
doubles' MIN_PARTY_SIZE) would otherwise shift everyone else's rank number
by their mere presence in one leaderboard and not the other, making swings
between formats look larger or smaller than they really are.

rank_delta = rank_a - rank_b, so positive means the trainer ranks better
(lower rank number) in format b than format a -- e.g. for singles/doubles,
positive means stronger relative to the field in doubles.

Trainers missing from one format entirely (e.g. a single-Pokemon party,
ineligible for doubles' MIN_PARTY_SIZE) are reported separately rather than
silently dropped.
"""
import argparse
import csv
import os

import results_lib


def rescale_ranks(board, shared):
    """Re-rank trainers by rating within just the shared set, so a rank_delta
    isn't skewed by trainers who only appear in one format's leaderboard."""
    ordered = sorted(shared, key=lambda trainer: board[trainer]["rating"], reverse=True)
    return {trainer: rank for rank, trainer in enumerate(ordered, start=1)}


def compare(fmt_a, fmt_b):
    board_a = results_lib.load_ratings(fmt_a)
    board_b = results_lib.load_ratings(fmt_b)

    shared = sorted(set(board_a) & set(board_b))
    only_a = sorted(set(board_a) - set(board_b))
    only_b = sorted(set(board_b) - set(board_a))

    rank_a = rescale_ranks(board_a, shared)
    rank_b = rescale_ranks(board_b, shared)

    comparisons = []
    for trainer in shared:
        a, b = board_a[trainer], board_b[trainer]
        comparisons.append({
            "trainer": trainer,
            f"rank_{fmt_a}": rank_a[trainer],
            f"rank_{fmt_b}": rank_b[trainer],
            "rank_delta": rank_a[trainer] - rank_b[trainer],
            f"rating_{fmt_a}": a["rating"],
            f"rating_{fmt_b}": b["rating"],
            f"battles_{fmt_a}": a["battles"],
            f"battles_{fmt_b}": b["battles"],
        })
    comparisons.sort(key=lambda row: abs(row["rank_delta"]), reverse=True)

    return comparisons, only_a, only_b


def write_outputs(fmt_a, fmt_b, comparisons, only_a, only_b):
    os.makedirs(results_lib.COMPARE_DIR, exist_ok=True)
    csv_path = os.path.join(results_lib.COMPARE_DIR, f"compare_{fmt_a}_{fmt_b}.csv")
    md_path = os.path.join(results_lib.COMPARE_DIR, f"compare_{fmt_a}_{fmt_b}.md")

    fieldnames = [
        "trainer", f"rank_{fmt_a}", f"rank_{fmt_b}", "rank_delta",
        f"rating_{fmt_a}", f"rating_{fmt_b}",
        f"battles_{fmt_a}", f"battles_{fmt_b}",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(comparisons)

    lines = [
        f"# Rank swing: {fmt_a} vs {fmt_b}",
        "",
        f"{len(comparisons)} trainers ranked in both formats. "
        f"{len(only_a)} only in {fmt_a}, {len(only_b)} only in {fmt_b}.",
        "",
        f"rank_delta = rank_{fmt_a} - rank_{fmt_b}: positive means the trainer "
        f"ranks better (lower number) in {fmt_b}.",
        "",
        f"Rating ({fmt_a})/({fmt_b}) columns are each format's own independent "
        f"Bradley-Terry fit, shown for reference only -- there's no shared "
        f"anchor between two separate fits, so their *difference* isn't a "
        f"meaningful quantity (see this script's module docstring). Rank is "
        f"the swing metric.",
        "",
        f"## Biggest swings toward {fmt_b}",
        "",
        f"| Trainer | Rank ({fmt_a}) | Rank ({fmt_b}) | Δrank | Rating ({fmt_a}) | Rating ({fmt_b}) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    toward_b = [row for row in comparisons if row["rank_delta"] > 0][:20]
    for row in toward_b:
        lines.append(
            f"| {row['trainer']} | {row[f'rank_{fmt_a}']} | {row[f'rank_{fmt_b}']} | "
            f"+{row['rank_delta']} | {row[f'rating_{fmt_a}']:.1f} | {row[f'rating_{fmt_b}']:.1f} |"
        )

    lines += [
        "",
        f"## Biggest swings toward {fmt_a}",
        "",
        f"| Trainer | Rank ({fmt_a}) | Rank ({fmt_b}) | Δrank | Rating ({fmt_a}) | Rating ({fmt_b}) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    toward_a = [row for row in comparisons if row["rank_delta"] < 0]
    toward_a.sort(key=lambda row: row["rank_delta"])
    for row in toward_a[:20]:
        lines.append(
            f"| {row['trainer']} | {row[f'rank_{fmt_a}']} | {row[f'rank_{fmt_b}']} | "
            f"{row['rank_delta']} | {row[f'rating_{fmt_a}']:.1f} | {row[f'rating_{fmt_b}']:.1f} |"
        )

    if only_a or only_b:
        lines += ["", "## Only ranked in one format", ""]
        if only_a:
            lines.append(f"Only in {fmt_a}: " + ", ".join(only_a))
        if only_b:
            lines.append(f"Only in {fmt_b}: " + ", ".join(only_b))

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return csv_path, md_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format-a", default="singles")
    parser.add_argument("--format-b", default="doubles")
    args = parser.parse_args()

    comparisons, only_a, only_b = compare(args.format_a, args.format_b)
    if not comparisons:
        print(f"No trainers found ranked in both {args.format_a} and {args.format_b} -- run ratings.py for both first.")
        return

    csv_path, md_path = write_outputs(args.format_a, args.format_b, comparisons, only_a, only_b)
    print(f"{len(comparisons)} trainers compared -> {csv_path}")
    print(f"-> {md_path}")
    biggest = comparisons[0]
    print(f"Biggest swing: {biggest['trainer']} "
          f"({args.format_a} #{biggest[f'rank_{args.format_a}']} -> {args.format_b} #{biggest[f'rank_{args.format_b}']})")


if __name__ == "__main__":
    main()
