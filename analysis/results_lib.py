#!/usr/bin/env python3
"""
Shared path/loader boilerplate for the analysis/*.py scripts: locating
elo_results_<format>_shard*.jsonl, discovering formats from them, loading a
format's ratings_<format>.json leaderboard, and loading the trainer-card
data dump. Pulled out once six different scripts (ratings.py, best_worst.py,
notable_matches.py, trainer_cards.py, level_plot.py, compare_formats.py) had
each grown their own near-identical copy.

Also owns the "cursed_excluded" post-hoc filter (drop every battle flagged
curse, see ratings.py's --exclude-cursed) and its one hand-maintained
special case: CURSE_NO_MERCY is sometimes only authored on one half of a
narratively-paired battle (e.g. Bence carries CURSE_NO_MERCY#1, his duo
partner Zoé doesn't), so a battle-level `curse` flag alone leaves Zoé's
non-Bence battles in the cursed_excluded fit while Bence's own disappear
entirely. Confirmed with Luna: cursed_excluded should be consistently
over-zealous rather than asymmetric, so both halves of a known pair are
excluded together.
"""
import glob
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(REPO_ROOT, "results", "remote")
CARD_DATA_PATH = os.path.join(REPO_ROOT, "vendor", "tectonic-content", "Analysis", "trainer_card_data.json")
CURSE_STRIP_DIFF_PATH = os.path.join(REPO_ROOT, "vendor", "tectonic-content", "Analysis", "curse_strip_diff.json")

WIN, LOSS, DRAW = 1, 2, 5

# Trainers whose only curse policy is CURSE_NO_MERCY (or a numbered variant)
# but who battle alongside a narratively-linked partner that carries no
# curse policy at all -- confirmed with Luna 2026-07-04, not derivable from
# the data alone (the two halves aren't linked by anything machine-readable,
# e.g. matching ExtendsVersion or trainer_type). Symmetric map so either
# label looks the other up.
ASYMMETRIC_CURSE_PAIRS = {
    "LEADER_Bence:Bence#1": "LEADER_Zoe:Zoé#1",
    "LEADER_Zoe:Zoé#1": "LEADER_Bence:Bence#1",
    "POKEMONTRAINER_Yezera:Yezera#11": "SHADOWMAVIS:Mavis#1",
    "SHADOWMAVIS:Mavis#1": "POKEMONTRAINER_Yezera:Yezera#11",
}


def discover_formats(results_dir=None):
    results_dir = results_dir or RESULTS_DIR
    formats = set()
    for path in glob.glob(os.path.join(results_dir, "elo_results_*_shard*.jsonl")):
        name = os.path.basename(path)
        # elo_results_<format>_shard<N>.jsonl
        middle = name[len("elo_results_"):-len(".jsonl")]
        formats.add(middle.rsplit("_shard", 1)[0])
    return sorted(formats)


def load_results(fmt, results_dir=None, report_skipped=False):
    """Every row from elo_results_<fmt>_shard*.jsonl, in shard/file order.
    A line caught mid-write by a still-live tournament run is incomplete
    JSON, not a real data problem -- silently skipped unless report_skipped."""
    results_dir = results_dir or RESULTS_DIR
    rows = []
    skipped_lines = 0
    for path in sorted(glob.glob(os.path.join(results_dir, f"elo_results_{fmt}_shard*.jsonl"))):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped_lines += 1
    if report_skipped and skipped_lines:
        print(f"  (skipped {skipped_lines} unparseable line(s), likely caught mid-write)")
    return rows


def load_ratings(fmt, suffix="", analysis_dir=None):
    analysis_dir = analysis_dir or ANALYSIS_DIR
    path = os.path.join(analysis_dir, f"ratings_{fmt}{suffix}.json")
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["trainer"]: row for row in rows}


def load_card_data(card_data_path=None):
    card_data_path = card_data_path or CARD_DATA_PATH
    with open(card_data_path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["label"]: row for row in rows}


def load_curse_strip_diff(path=None):
    """label -> classifyCursedTrainer's dump (curses, base, identical_to_base,
    no_change_from_original, diffs_vs_base) for every cursed trainer -- see
    curse_stripping.rb. Only cursed trainers appear; everyone else is absent."""
    path = path or CURSE_STRIP_DIFF_PATH
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_cursed_excluded(row):
    """cursed_excluded's row-level filter predicate: drop battles flagged
    curse, plus battles involving the non-curse-flagged half of an
    ASYMMETRIC_CURSE_PAIRS pair (see module docstring)."""
    if row.get("curse"):
        return True
    t1, t2 = row.get("trainer1"), row.get("trainer2")
    return t1 in ASYMMETRIC_CURSE_PAIRS or t2 in ASYMMETRIC_CURSE_PAIRS
