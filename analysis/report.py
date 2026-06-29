#!/usr/bin/env python3
"""
Markdown leaderboard report, built from ratings.py's output.

Reads analysis/ratings_<format>.json (run ratings.py first) and writes
analysis/report_<format>.md -- a plain Markdown table, full leaderboard,
one file per format. Presentation only; all the actual rating math
lives in ratings.py.
"""
import argparse
import glob
import json
import os

ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))


def discover_formats():
    formats = []
    for path in sorted(glob.glob(os.path.join(ANALYSIS_DIR, "ratings_*.json"))):
        name = os.path.basename(path)
        formats.append(name[len("ratings_"):-len(".json")])
    return formats


def write_report(fmt):
    json_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}.json")
    with open(json_path, "r", encoding="utf-8") as f:
        leaderboard = json.load(f)

    md_path = os.path.join(ANALYSIS_DIR, f"report_{fmt}.md")
    total_battles = sum(row["battles"] for row in leaderboard) // 2

    lines = [
        f"# ELO Tournament Leaderboard -- {fmt}",
        "",
        f"{len(leaderboard)} trainers, {total_battles} battles.",
        "",
        "95% CI from the fit's own Laplace approximation; Overlap is how many "
        "*other* trainers' rating falls inside this trainer's CI -- a high "
        "count means their exact rank shouldn't be read as precise.",
        "",
        "| Rank | Trainer | Rating | 95% CI | Overlap | W | L | D | Battles |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in leaderboard:
        lines.append(
            f"| {row['rank']} | {row['trainer']} | {row['rating']:.1f} "
            f"| {row['ci_low']:.0f} - {row['ci_high']:.0f} | {row['overlap']} "
            f"| {row['wins']} | {row['losses']} | {row['draws']} | {row['battles']} |"
        )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return md_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", help="Only report this format (default: all ratings_*.json found)")
    args = parser.parse_args()

    formats = [args.format] if args.format else discover_formats()
    if not formats:
        print("No ratings_*.json found in analysis/ -- run ratings.py first.")
        return

    for fmt in formats:
        md_path = write_report(fmt)
        print(f"[{fmt}] -> {md_path}")


if __name__ == "__main__":
    main()
