#!/usr/bin/env python3
"""
Shared path/loader boilerplate for the analysis/*.py scripts: locating
elo_results_<format>_shard*.jsonl, discovering formats from them, loading a
format's ratings_<format>.json leaderboard, and loading the trainer-card
data dump. Pulled out once six different scripts (ratings.py, best_worst.py,
notable_matches.py, trainer_cards.py, level_plot.py, compare_formats.py) had
each grown their own near-identical copy.

Also owns the named row-level filter registry (FILTERS) shared by every
script that lets you narrow a fit or lookup to a subset of battles --
cursed_excluded (drop every battle flagged curse) and level70_only (keep
only battles between two 6-Pokemon-at-level-70 "endgame" trainers) as of
this writing -- plus add_filter_arg/filter_suffix/passes_filters/
load_card_data_if_needed, the shared CLI-flag-to-filename-suffix plumbing
so ratings.py, best_worst.py, and custom_trainer_report.py all pick
ratings_<fmt>_<name1>_<name2>...json the same way instead of each growing
its own --exclude-cursed-shaped flag.

cursed_excluded has one hand-maintained special case: CURSE_NO_MERCY is
sometimes only authored on one half of a narratively-paired battle (e.g.
Bence carries CURSE_NO_MERCY#1, his duo partner Zoé doesn't), so a
battle-level `curse` flag alone leaves Zoé's non-Bence battles in the
cursed_excluded fit while Bence's own disappear entirely. Confirmed with
Luna: cursed_excluded should be consistently over-zealous rather than
asymmetric, so both halves of a known pair are excluded together.
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

# The curse-stripped tournament's raw per-shard output (elo_results_<fmt>_
# uncursed_raw_shard*.jsonl) is a partial re-battled subset, not a full round
# robin -- coherent only once build_uncursed_results.py merges it into the
# base format's results as elo_results_<fmt>_uncursed_shard0.jsonl (see
# project_curse_stripping_format.md). Excluded from default (no --format)
# discovery so it never gets its own standalone ratings by accident; still
# reachable via an explicit --format for debugging.
RAW_ONLY_SUFFIX = "_uncursed_raw"


def is_raw_only_format(fmt):
    return fmt.endswith(RAW_ONLY_SUFFIX)

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


def _is_sidecar_file(path):
    """dedupe_results.py/strip_had_error.py back up removed rows to
    <file>.duplicates_removed.jsonl / <file>.had_error_removed.jsonl next to
    the original -- both still end in ".jsonl", so a naive glob.glob(
    "elo_results_<fmt>_shard*.jsonl") matches them too (glob's "*" crosses
    "."), silently re-including rows that were deliberately removed."""
    return ".duplicates_removed" in path or ".had_error_removed" in path


def discover_formats(results_dir=None):
    results_dir = results_dir or RESULTS_DIR
    formats = set()
    for path in glob.glob(os.path.join(results_dir, "elo_results_*_shard*.jsonl")):
        if _is_sidecar_file(path):
            continue
        name = os.path.basename(path)
        # elo_results_<format>_shard<N>.jsonl
        middle = name[len("elo_results_"):-len(".jsonl")]
        fmt = middle.rsplit("_shard", 1)[0]
        if is_raw_only_format(fmt):
            continue
        formats.add(fmt)
    return sorted(formats)


def load_results(fmt, results_dir=None, report_skipped=False):
    """Every row from elo_results_<fmt>_shard*.jsonl, in shard/file order.
    A line caught mid-write by a still-live tournament run is incomplete
    JSON, not a real data problem -- silently skipped unless report_skipped."""
    results_dir = results_dir or RESULTS_DIR
    rows = []
    skipped_lines = 0
    for path in sorted(glob.glob(os.path.join(results_dir, f"elo_results_{fmt}_shard*.jsonl"))):
        if _is_sidecar_file(path):
            continue
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


def is_level70_trainer(label, card_data):
    """True if `label` fields exactly 6 Pokemon, all at level 70 -- the
    "endgame/developer team" cohort used by the level70_only filter. There's
    no in-game "developer" trainer type to key off (it's just an informal
    label people put on trainers of various real types), so this is derived
    purely from the dumped party data."""
    row = card_data.get(label)
    if row is None:
        return False
    party = row.get("party") or []
    return len(party) == 6 and all(p.get("level") == 70 for p in party)


# Named row-level "keep this battle" predicates shared by ratings.py,
# best_worst.py, and custom_trainer_report.py's --filter flag, each keyed by
# the name used in its output suffix (ratings_<fmt>_<name>.json). A
# predicate takes (row, card_data) and returns True to keep the row.
# card_data is only loaded (via load_card_data_if_needed) if some active
# filter's FILTERS_NEEDING_CARD_DATA entry says it's needed, since most
# rows/filters don't need per-trainer party data.
FILTERS = {
    "cursed_excluded": lambda row, card_data: not is_cursed_excluded(row),
    "level70_only": lambda row, card_data: (
        is_level70_trainer(row["trainer1"], card_data)
        and is_level70_trainer(row["trainer2"], card_data)
    ),
}
FILTERS_NEEDING_CARD_DATA = {"level70_only"}


def add_filter_arg(parser):
    """Shared --filter CLI flag: a repeatable named row-level filter (see
    FILTERS) that also picks the ratings_<fmt><filter_suffix(...)>.json/csv
    file a script reads and/or writes, instead of each script growing its
    own --exclude-cursed-shaped boolean flag."""
    parser.add_argument(
        "--filter", action="append", default=[], metavar="NAME", choices=sorted(FILTERS),
        help=(
            "Named filter (repeatable); see results_lib.FILTERS for definitions. Determines the "
            "ratings_<fmt>_<name1>_<name2>...json/csv file this reads and/or writes instead of "
            "the unfiltered one, with names joined in FILTERS' own order regardless of flag order."
        ),
    )


def filter_suffix(filter_names):
    """Canonical suffix for a set of active filter names, in FILTERS' own
    order (not caller order) so e.g. --filter level70_only --filter
    cursed_excluded and the reverse both produce
    _cursed_excluded_level70_only."""
    return "".join(f"_{name}" for name in FILTERS if name in filter_names)


def load_card_data_if_needed(filter_names, card_data_path=None):
    """load_card_data() only if some active filter actually needs it (see
    FILTERS_NEEDING_CARD_DATA) -- so a script that never uses level70_only
    doesn't pay to load and index trainer_card_data.json for nothing."""
    if any(name in FILTERS_NEEDING_CARD_DATA for name in filter_names):
        return load_card_data(card_data_path)
    return None


def passes_filters(row, filter_names, card_data):
    """True if row survives every active named filter (see FILTERS)."""
    return all(FILTERS[name](row, card_data) for name in filter_names)
