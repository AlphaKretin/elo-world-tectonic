#!/usr/bin/env python3
"""
Markdown bracket report, built from bracket.rb's
results/bracket_<format>_results.tsv. Renders each completed round as its
own table -- safe to run mid-bracket, later rounds just don't appear yet.
Presentation only, mirrors report.py's role for the round-robin leaderboard.
"""
import argparse
import csv
import glob
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))

FIELDS = [
    "round", "round_name", "match",
    "seed1", "trainer1", "seed2", "trainer2",
    "winner_seed", "winner", "loser_seed", "loser",
    "result", "rounds", "time_s", "had_error", "attempts", "decided_by", "replay_path",
]


def discover_formats():
    formats = []
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, "bracket_*_results.tsv"))):
        name = os.path.basename(path)
        formats.append(name[len("bracket_"):-len("_results.tsv")])
    return formats


def load_matches(fmt):
    path = os.path.join(RESULTS_DIR, f"bracket_{fmt}_results.tsv")
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, fieldnames=FIELDS, delimiter="\t"))


def write_report(fmt):
    matches = load_matches(fmt)
    by_round = {}
    for m in matches:
        by_round.setdefault((int(m["round"]), m["round_name"]), []).append(m)

    lines = [f"# ELO Tournament Bracket -- {fmt}", ""]
    champion = None
    body = []
    for (round_num, round_name), round_matches in sorted(by_round.items()):
        round_matches.sort(key=lambda m: int(m["match"]))
        body += [
            f"## {round_name}", "",
            "| Match | Seed | Trainer | | Seed | Trainer | Winner | Decided by | Replay |",
            "|---:|---:|---|---|---:|---|---|---|---|",
        ]
        for m in round_matches:
            replay = os.path.basename(m["replay_path"]) if m["replay_path"] else "(none)"
            body.append(
                f"| {m['match']} | {m['seed1']} | {m['trainer1']} | vs | {m['seed2']} | {m['trainer2']} "
                f"| **{m['winner']}** | {m['decided_by']} | {replay} |"
            )
        body.append("")
        if len(round_matches) == 1:
            champion = round_matches[0]["winner"]

    if champion:
        lines += [f"**Champion: {champion}**", ""]
    lines += body

    md_path = os.path.join(ANALYSIS_DIR, f"bracket_report_{fmt}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return md_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", help="Only report this format (default: all bracket_*_results.tsv found)")
    args = parser.parse_args()

    formats = [args.format] if args.format else discover_formats()
    if not formats:
        print("No bracket_*_results.tsv found in results/ -- run the bracket first.")
        return

    for fmt in formats:
        md_path = write_report(fmt)
        print(f"[{fmt}] -> {md_path}")


if __name__ == "__main__":
    main()
