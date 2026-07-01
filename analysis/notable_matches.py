#!/usr/bin/env python3
"""
Surfaces "notable" battles from the results pool, worth a closer look or a
saved replay (see scripts/save_replay.ps1) -- a discovery/curation tool,
not a ranking signal like ratings.py. Categories so far (designing more is
an ongoing thing, not meant to be exhaustive):

- Upsets: the winner was rated much lower than the loser.
- Self-mirror losses: a trainer's cursed/extended version lost to the
  *exact* plain version it extends (see fight_pairs -- same identity,
  consecutive base+CURSE_* versions, not just any two versions of the
  same character at different points in their story) -- the curse is
  supposed to be in that side's favor, so this runs backwards. Exhaustive,
  not top-N -- there's no "how cursed" scale to rank by, it either
  happened or it didn't.
- Extreme battle length: very long grinds are notable on their own
  regardless of team size or rating gap, but a very fast finish is only
  notable when it's *between closely-rated opponents* AND relative to how
  many Pokemon the loser actually had -- a 1-Pokemon trainer losing in
  round 1 isn't surprising on its own, and a quick stomp by a heavy
  favorite is just the upset category (or nothing) wearing a different hat.

Run after ratings.py (needs ratings_<format>.json) against
results/remote/elo_results_<format>_shard*.jsonl (default; use
--results-dir results/ for local shard data) and
vendor/tectonic-content/Analysis/trainer_card_data.json (for per-trainer
curse/identity lookups, the same dump trainer_cards.py uses). Writes
analysis/notable_matches_<format>.md.

The current results are a stale, incomplete sample (see project notes) --
treat anything this turns up right now as a check that the script runs,
not as a real finding. Re-run once the dataset is actually valid.
"""
import argparse
import glob
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(REPO_ROOT, "results", "remote")
CARD_DATA_PATH = os.path.join(REPO_ROOT, "vendor", "tectonic-content", "Analysis", "trainer_card_data.json")

WIN, LOSS, DRAW = 1, 2, 5


def discover_formats():
    formats = set()
    for path in glob.glob(os.path.join(RESULTS_DIR, "elo_results_*_shard*.jsonl")):
        name = os.path.basename(path)
        middle = name[len("elo_results_"):-len(".jsonl")]
        formats.add(middle.rsplit("_shard", 1)[0])
    return sorted(formats)


def load_ratings(fmt):
    path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}.json")
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["trainer"]: row for row in rows}


def load_card_data():
    with open(CARD_DATA_PATH, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["label"]: row for row in rows}


def load_results(fmt):
    rows = []
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, f"elo_results_{fmt}_shard*.jsonl"))):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def decisive_rows(rows):
    for r in rows:
        if r.get("skipped") or r.get("had_error") or r.get("result") not in (WIN, LOSS):
            continue
        yield r


def is_cursed(card_row):
    return any(p.startswith("CURSE_") for p in card_row["policies"])


def identity_key(card_row):
    return (card_row["trainer_type"], card_row.get("name_for_hashing") or card_row["real_name"])


def fight_pairs(card_data):
    """{label: partner_label} for labels that are exactly each other's
    base/cursed-extension pair -- the *same* fight, not just the same
    identity at a different point in their story (e.g. Helena#0/#1 are a
    pair at Lv.25; Helena#2/#3 are a separate, later pair at Lv.70 --
    Helena#2 beating cursed Helena#1 isn't curse irony, just two different
    fights). Mirrors trainer_cards.py's distinct_fight_number grouping:
    within an identity, walk versions in order and attach each cursed
    entry to the nearest preceding non-cursed one."""
    groups = {}
    for row in card_data.values():
        groups.setdefault(identity_key(row), []).append(row)

    pairs = {}
    for group_rows in groups.values():
        group_rows.sort(key=lambda r: r["version"])
        last_base_label = None
        for row in group_rows:
            if is_cursed(row):
                if last_base_label is not None:
                    pairs[row["label"]] = last_base_label
                    pairs[last_base_label] = row["label"]
            else:
                last_base_label = row["label"]
    return pairs


def replay_cmd(t1, t2, seed, fmt):
    extra = "" if fmt == "singles" else f' -Format "{fmt}"'
    return f'.\\scripts\\save_replay.ps1 -Trainer1 "{t1}" -Trainer2 "{t2}" -Seed {seed}{extra}'


def round_count(n):
    return f"{n} round" if n == 1 else f"{n} rounds"


def find_upsets(rows, ratings, top_n):
    """Decisive battles where the winner's own rating was below the
    loser's, sorted by how large that gap was."""
    upsets = []
    for r in decisive_rows(rows):
        t1, t2 = r["trainer1"], r["trainer2"]
        winner, loser = (t1, t2) if r["result"] == WIN else (t2, t1)
        wr, lr = ratings.get(winner), ratings.get(loser)
        if not wr or not lr:
            continue
        gap = lr["rating"] - wr["rating"]
        if gap > 0:
            upsets.append({"row": r, "winner": winner, "loser": loser, "gap": gap, "wr": wr, "lr": lr})
    upsets.sort(key=lambda u: -u["gap"])
    return upsets[:top_n]


def find_self_mirror_losses(rows, card_data, ratings):
    """Exact base/cursed-extension fight pairs (see fight_pairs) where the
    cursed side lost to its own plain original."""
    pairs = fight_pairs(card_data)
    found = []
    for r in decisive_rows(rows):
        t1, t2 = r["trainer1"], r["trainer2"]
        if t1 == t2 or pairs.get(t1) != t2:
            continue
        cursed_label, plain_label = (t1, t2) if is_cursed(card_data[t1]) else (t2, t1)
        winner = t1 if r["result"] == WIN else t2
        if cursed_label == winner:
            continue  # curse won -- not the anomaly we're after
        found.append({
            "row": r, "winner": plain_label, "loser": cursed_label,
            "wr": ratings.get(plain_label), "lr": ratings.get(cursed_label),
        })
    return found


def find_extreme_length(rows, ratings, card_data, top_n):
    """(longest grinds, fastest finishes). Longest is plain rounds-
    descending -- a long battle is notable on its own regardless of team
    size. Fastest ranks by the *combined* percentile rank of low
    rounds-per-loser-Pokemon and low rating gap (not raw rounds) --
    comparing percentile ranks rather than raw values sidesteps the
    normalized speed (a small fraction) and Elo gap (often hundreds)
    trading off unevenly in a naive sum. Rounds alone mostly just found
    the loser's party size: a 1-Pokemon trainer losing in round 1 isn't
    surprising, a 6-Pokemon trainer getting swept that fast is."""
    decisive = []
    for r in decisive_rows(rows):
        t1, t2 = r["trainer1"], r["trainer2"]
        winner, loser = (t1, t2) if r["result"] == WIN else (t2, t1)
        wr, lr = ratings.get(winner), ratings.get(loser)
        loser_card = card_data.get(loser)
        if not wr or not lr or not loser_card:
            continue
        loser_party_size = len(loser_card["party"]) or 1
        decisive.append({"row": r, "winner": winner, "loser": loser, "wr": wr, "lr": lr,
                          "rounds": r["rounds"], "gap": abs(wr["rating"] - lr["rating"]),
                          "loser_party_size": loser_party_size,
                          "speed": r["rounds"] / loser_party_size})

    longest = sorted(decisive, key=lambda d: -d["rounds"])[:top_n]

    by_speed = sorted(range(len(decisive)), key=lambda i: decisive[i]["speed"])
    by_gap = sorted(range(len(decisive)), key=lambda i: decisive[i]["gap"])
    speed_rank, gap_rank = [0] * len(decisive), [0] * len(decisive)
    for rank, i in enumerate(by_speed):
        speed_rank[i] = rank
    for rank, i in enumerate(by_gap):
        gap_rank[i] = rank
    fastest_order = sorted(range(len(decisive)), key=lambda i: speed_rank[i] + gap_rank[i])[:top_n]
    fastest = [decisive[i] for i in fastest_order]

    return longest, fastest


def write_report(fmt, upsets, self_mirror, longest, fastest):
    lines = [f"# Notable matches -- {fmt}", ""]

    lines += ["## Upsets", "", "Winner rated below the loser, largest gap first.", ""]
    for u in upsets:
        r = u["row"]
        lines.append(
            f"- **{u['winner']}** ({u['wr']['rating']:.0f}) beat **{u['loser']}** ({u['lr']['rating']:.0f}), "
            f"gap {u['gap']:.0f}, {round_count(r['rounds'])}\n"
            f"  `{replay_cmd(r['trainer1'], r['trainer2'], r['seed'], fmt)}`"
        )

    lines += ["", "## Self-mirror losses", "",
              "Exact base/cursed-extension fight pairs -- the cursed side lost to its own plain original.", ""]
    if not self_mirror:
        lines.append("(none found)")
    for u in self_mirror:
        r = u["row"]
        wr_text = f" ({u['wr']['rating']:.0f})" if u["wr"] else ""
        lr_text = f" ({u['lr']['rating']:.0f})" if u["lr"] else ""
        lines.append(
            f"- **{u['winner']}**{wr_text} beat cursed **{u['loser']}**{lr_text}, {round_count(r['rounds'])}\n"
            f"  `{replay_cmd(r['trainer1'], r['trainer2'], r['seed'], fmt)}`"
        )

    lines += ["", "## Longest grinds", "", "Most rounds, notable regardless of rating gap.", ""]
    for d in longest:
        r = d["row"]
        lines.append(
            f"- {round_count(r['rounds'])}: **{d['winner']}** ({d['wr']['rating']:.0f}) beat "
            f"**{d['loser']}** ({d['lr']['rating']:.0f}), gap {d['gap']:.0f}\n"
            f"  `{replay_cmd(r['trainer1'], r['trainer2'], r['seed'], fmt)}`"
        )

    lines += ["", "## Fastest finishes between close opponents", "",
              "Ranked by combined rank of low rounds-per-loser-Pokemon *and* low rating gap -- a fast "
              "stomp by a heavy favorite isn't surprising (that's the upset category), and neither is a "
              "fast finish where the loser only had one or two Pokemon to begin with.", ""]
    for d in fastest:
        r = d["row"]
        lines.append(
            f"- {round_count(r['rounds'])} for a {d['loser_party_size']}-Pokemon loser, gap {d['gap']:.0f}: "
            f"**{d['winner']}** ({d['wr']['rating']:.0f}) beat **{d['loser']}** ({d['lr']['rating']:.0f})\n"
            f"  `{replay_cmd(r['trainer1'], r['trainer2'], r['seed'], fmt)}`"
        )

    md_path = os.path.join(ANALYSIS_DIR, f"notable_matches_{fmt}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return md_path


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", help="Only this format (default: all formats with a ratings_*.json found)")
    parser.add_argument("--top", type=int, default=15, help="How many matches per top-N category (default: 15)")
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    formats = [args.format] if args.format else discover_formats()
    if not formats:
        print(f"No elo_results_*_shard*.jsonl found under {RESULTS_DIR}.")
        return
    if not os.path.exists(CARD_DATA_PATH):
        raise SystemExit(f"{CARD_DATA_PATH} not found -- run the ELO_DUMP_TRAINER_CARD_DATA dump first.")
    card_data = load_card_data()

    for fmt in formats:
        ratings_path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}.json")
        if not os.path.exists(ratings_path):
            print(f"[{fmt}] No {ratings_path} -- run ratings.py first. Skipping.")
            continue
        ratings = load_ratings(fmt)
        rows = load_results(fmt)

        upsets = find_upsets(rows, ratings, args.top)
        self_mirror = find_self_mirror_losses(rows, card_data, ratings)
        longest, fastest = find_extreme_length(rows, ratings, card_data, args.top)

        md_path = write_report(fmt, upsets, self_mirror, longest, fastest)
        print(f"[{fmt}] {len(upsets)} upsets, {len(self_mirror)} self-mirror losses, "
              f"top {len(longest)} longest, top {len(fastest)} fastest-close -> {md_path}")


if __name__ == "__main__":
    main()
