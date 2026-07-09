#!/usr/bin/env python3
"""
Shared path/loader boilerplate for the analysis/*.py scripts: locating
elo_results_<format>_shard*.jsonl, discovering formats from them, loading a
format's ratings_<format>.json leaderboard, and loading the per-trainer
data dump. Pulled out once six different scripts (ratings.py, best_worst.py,
notable_matches.py, trainer_cards.py, level_plot.py, compare_formats.py) had
each grown their own near-identical copy.

Also owns the named row-level filter registry (FILTERS) shared by every
script that lets you narrow a fit or lookup to a subset of battles --
cursed_excluded (drop every battle flagged curse), level70_only (keep
only battles between two 6-Pokemon-at-level-70 "endgame" trainers), and
developer_only (keep only battles between two TrainerTypeLabel=DEVELOPER
trainers -- overlaps heavily with level70_only but isn't identical, since
DEVELOPER is a display-label override, not tied to party composition) as
of this writing -- plus add_filter_arg/filter_suffix/passes_filters/
load_trainer_data_if_needed, the shared CLI-flag-to-filename-suffix plumbing
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
RESULTS_DIR = os.path.join(REPO_ROOT, "results", "current")
# trainer_data.json / curse_strip_diff.json ground truth lives in
# results/current alongside the battle shards, not in the vendor submodule's
# gitignored Analysis/ staging folder -- the game dumps a fresh copy there
# (EloTournament.dumpTrainerCardData! / curse_stripping.rb), and promoting it
# into results/current is a manual step, same as results/local -> current.
TRAINER_DATA_PATH = os.path.join(RESULTS_DIR, "trainer_data.json")
CURSE_STRIP_DIFF_PATH = os.path.join(RESULTS_DIR, "curse_strip_diff.json")

# Generated-output subfolders, one per kind, so analysis/ itself holds only
# scripts (+ card_constants.py) -- everything these scripts write lives
# under one of these instead of loose in analysis/ root.
RATINGS_DIR = os.path.join(ANALYSIS_DIR, "ratings")
BEST_WORST_DIR = os.path.join(ANALYSIS_DIR, "best_worst")
REPORTS_DIR = os.path.join(ANALYSIS_DIR, "reports")
COMPARE_DIR = os.path.join(ANALYSIS_DIR, "compare")
NOTABLE_MATCHES_DIR = os.path.join(ANALYSIS_DIR, "notable_matches")
CUSTOM_TRAINER_DIR = os.path.join(ANALYSIS_DIR, "custom_trainer")
CARDS_DIR = os.path.join(ANALYSIS_DIR, "cards")

WIN, LOSS, DRAW = 1, 2, 5

# elo_results_<fmt>_uncursed_shard*.jsonl on disk is ALWAYS the raw
# curse-stripped partial re-battle subset (only pairings where stripping
# curses actually changed a party get re-battled -- see tournament.rb) --
# never a full round robin. load_results() merges it with the base format's
# curse:false population in memory on every call (see _merge_uncursed) so
# there's no separate merged artifact that can go stale (see
# project_curse_stripping_format.md / project_uncursed_data_staleness.md).
UNCURSED_SUFFIX = "_uncursed"


def is_uncursed_format(fmt):
    return fmt.endswith(UNCURSED_SUFFIX)

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
        formats.add(fmt)
    return sorted(formats)


def pair_key(row):
    """Unordered (trainer1, trainer2) identity for a battle row -- shared by
    _merge_uncursed and by ratings.py's compute_anchored_uncursed_pair,
    which needs the same shared-vs-differing-battle split to anchor a
    cursed/uncursed pair's fits to a common reference point."""
    return frozenset((row.get("trainer1"), row.get("trainer2")))


def _merge_uncursed(base_rows, raw_rows, results_dir=None):
    """Merge rule per pairing (confirmed with Luna 2026-07-04):
      1. curse:false rows carry over unchanged.
      2. curse:true rows are replaced by the matching pairing's row in the
         raw curse-stripped results, if one exists there (only pairings
         where at least one side's stripped party actually changed get
         re-battled -- see tournament.rb).
      3. curse:true rows with no raw counterpart are pairings where
         stripping was a no-op for both sides -- kept as-is, UNLESS either
         trainer is "identical_to_base" per curse_strip_diff.json (their
         stripped form duplicates another pool member exactly, so they're
         excluded from the uncursed pool entirely as a redundant opponent).
      4. Every row from the raw curse-stripped results is included."""
    diff = load_curse_strip_diff(results_dir=results_dir)
    identical_to_base = {label for label, info in diff.items() if info.get("identical_to_base")}
    raw_pairs = {pair_key(r) for r in raw_rows}

    merged = []
    for row in base_rows:
        if not row.get("curse"):
            merged.append(row)
            continue
        if pair_key(row) in raw_pairs:
            continue
        t1, t2 = row.get("trainer1"), row.get("trainer2")
        if t1 in identical_to_base or t2 in identical_to_base:
            continue
        merged.append(row)
    merged.extend(raw_rows)
    return merged


# (results_dir, fmt) -> (signature, rows). A single process (viewer GUI or
# a one-shot analysis script) can end up calling load_results for the same
# format many times over -- e.g. the viewer's Browse/Trainers/Bracket tabs
# each load independently at boot, and an "..._uncursed" format's own load
# recurses into its base format's -- so this avoids re-reading and
# re-json.loads-ing the same shard files from disk repeatedly. Safe to
# share the returned list/dicts across every caller as long as nothing
# mutates them in place (confirmed: nothing in this codebase does).
_shard_cache = {}


def clear_cache():
    """Drops every cached load_shard_files() result. The signature check in
    load_shard_files already re-reads automatically if a shard file's mtime
    or size changed, so this isn't needed for correctness in the common
    case -- it exists as an explicit "no really, forget what you had"
    escape hatch for the viewer's Refresh buttons, since same-second mtimes
    (a fast regeneration landing within one mtime tick) could otherwise slip
    past the signature check."""
    _shard_cache.clear()


def _shard_files_signature(paths):
    return tuple((path, os.path.getmtime(path), os.path.getsize(path)) for path in paths)


def load_shard_files(fmt, results_dir, report_skipped=False):
    """Every row from elo_results_<fmt>_shard*.jsonl, in shard/file order.
    A line caught mid-write by a still-live tournament run is incomplete
    JSON, not a real data problem -- silently skipped unless report_skipped."""
    paths = [
        path for path in sorted(glob.glob(os.path.join(results_dir, f"elo_results_{fmt}_shard*.jsonl")))
        if not _is_sidecar_file(path)
    ]
    signature = _shard_files_signature(paths)
    cache_key = (results_dir, fmt)
    cached = _shard_cache.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    rows = []
    skipped_lines = 0
    for path in paths:
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
    _shard_cache[cache_key] = (signature, rows)
    return rows


def load_results(fmt, results_dir=None, report_skipped=False):
    """Every row for format `fmt`. For a plain format this is just its
    elo_results_<fmt>_shard*.jsonl shards; for an "..._uncursed" format
    this is that same on-disk partial subset merged in memory with the
    base format's curse:false population (see _merge_uncursed) -- there is
    no separate "full" file for an uncursed format on disk."""
    results_dir = results_dir or RESULTS_DIR
    if is_uncursed_format(fmt):
        raw_rows = load_shard_files(fmt, results_dir, report_skipped)
        base_fmt = fmt[:-len(UNCURSED_SUFFIX)]
        base_rows = load_results(base_fmt, results_dir=results_dir, report_skipped=report_skipped)
        return _merge_uncursed(base_rows, raw_rows, results_dir=results_dir)
    return load_shard_files(fmt, results_dir, report_skipped)


def find_had_error_rows(results_dir=None):
    """Every had_error:true row across every discovered format's raw shard
    files (including _uncursed formats' own raw partial files, scanned
    directly rather than through the in-memory uncursed merge, since a
    had_error row needs fixing on disk regardless of which merged view would
    show it). Used by export_web_data.py to hard-fail before publishing --
    a had_error row (whether a recoverable engine hiccup with a result
    attached, or a repeated-crash row with result:null) sat undetected in
    results/current for an unknown length of time once before (see
    strip_had_error.py's existence), so publishing must refuse to proceed
    silently rather than warn."""
    results_dir = results_dir or RESULTS_DIR
    errors = []
    for fmt in discover_formats(results_dir):
        for row in load_shard_files(fmt, results_dir):
            if row.get("had_error"):
                errors.append((fmt, row))
    return errors


def load_ratings(fmt, suffix="", ratings_dir=None):
    ratings_dir = ratings_dir or RATINGS_DIR
    path = os.path.join(ratings_dir, f"ratings_{fmt}{suffix}.json")
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["trainer"]: row for row in rows}


def load_trainer_data(trainer_data_path=None, results_dir=None):
    trainer_data_path = trainer_data_path or (
        os.path.join(results_dir, "trainer_data.json") if results_dir else TRAINER_DATA_PATH
    )
    with open(trainer_data_path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["label"]: row for row in rows}


def load_curse_strip_diff(path=None, results_dir=None):
    """label -> classifyCursedTrainer's dump (curses, base, identical_to_base,
    no_change_from_original, diffs_vs_base) for every cursed trainer -- see
    curse_stripping.rb. Only cursed trainers appear; everyone else is absent."""
    path = path or (
        os.path.join(results_dir, "curse_strip_diff.json") if results_dir else CURSE_STRIP_DIFF_PATH
    )
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


def is_level70_trainer(label, trainer_data):
    """True if `label` fields exactly 6 Pokemon, all at level 70 -- the
    "endgame/developer team" cohort used by the level70_only filter. There's
    no in-game "developer" trainer type to key off (it's just an informal
    label people put on trainers of various real types), so this is derived
    purely from the dumped party data."""
    row = trainer_data.get(label)
    if row is None:
        return False
    party = row.get("party") or []
    return len(party) == 6 and all(p.get("level") == 70 for p in party)


def is_developer_trainer(label, trainer_data):
    """True if `label` carries the TrainerTypeLabel = DEVELOPER override --
    a display-only label (see custom_trainer.rb/Trainer.rb) that swaps the
    shown trainer type name while keeping the original sprite, not a real
    TrainerType. Used by the developer_only filter to isolate the
    "actual person" cohort (distinct from level70_only's endgame-team
    cohort, though the two overlap significantly)."""
    row = trainer_data.get(label)
    if row is None:
        return False
    return row.get("trainer_type_label") == "DEVELOPER"


def is_cursed_trainer(label, trainer_data):
    """True if `label` has an authored CURSE_* policy active (the same
    "isCursed" check export_web_data.py's static_trainer_payload shows on
    the website's trainer cards) -- not to be confused with a battle-level
    `curse` flag, which also fires for a curse-free trainer paired against
    a cursed one."""
    row = trainer_data.get(label)
    if row is None:
        return False
    return any(p.startswith("CURSE_") for p in row.get("policies") or [])


# Filters in here have a fixed "both sides must be in this cohort" shape
# keyed off a per-trainer predicate (unlike cursed_excluded, which is a
# row-level curse-drop with no fixed trainer population of its own) -- see
# filter_has_cursed_population, which uses this registry to decide whether
# publishing an _uncursed variant of one of these filters would actually
# differ from its plain cursed default.
FILTER_TRAINER_PREDICATES = {
    "level70_only": is_level70_trainer,
    "developer_only": is_developer_trainer,
}


def filter_has_cursed_population(name, trainer_data):
    """True if filter `name`'s trainer cohort (see FILTER_TRAINER_PREDICATES)
    contains at least one authored-curse trainer. A curse-stripped _uncursed
    rebattle only changes cursed trainers' own battles, so if a filter's
    cohort has none, its _uncursed variant is byte-identical to the plain
    cursed default -- export_web_data.py uses this to skip publishing that
    redundant duplicate (e.g. developer_only: no developer trainer is
    cursed, so singles_uncursed_developer_only would just be a copy of
    singles_developer_only) and the website falls back cursed instead (see
    web/src/lib/formatValidity.ts's nearestValidFormat)."""
    predicate = FILTER_TRAINER_PREDICATES[name]
    return any(
        predicate(label, trainer_data) and is_cursed_trainer(label, trainer_data)
        for label in trainer_data
    )


# Named row-level "keep this battle" predicates shared by ratings.py,
# best_worst.py, and custom_trainer_report.py's --filter flag, each keyed by
# the name used in its output suffix (ratings_<fmt>_<name>.json). A
# predicate takes (row, trainer_data) and returns True to keep the row.
# trainer_data is only loaded (via load_trainer_data_if_needed) if some active
# filter's FILTERS_NEEDING_TRAINER_DATA entry says it's needed, since most
# rows/filters don't need per-trainer party data.
FILTERS = {
    "cursed_excluded": lambda row, trainer_data: not is_cursed_excluded(row),
    "level70_only": lambda row, trainer_data: (
        is_level70_trainer(row["trainer1"], trainer_data)
        and is_level70_trainer(row["trainer2"], trainer_data)
    ),
    "developer_only": lambda row, trainer_data: (
        is_developer_trainer(row["trainer1"], trainer_data)
        and is_developer_trainer(row["trainer2"], trainer_data)
    ),
}
FILTERS_NEEDING_TRAINER_DATA = {"level70_only", "developer_only"}


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


def load_trainer_data_if_needed(filter_names, trainer_data_path=None):
    """load_trainer_data() only if some active filter actually needs it (see
    FILTERS_NEEDING_TRAINER_DATA) -- so a script that never uses level70_only
    doesn't pay to load and index trainer_data.json for nothing."""
    if any(name in FILTERS_NEEDING_TRAINER_DATA for name in filter_names):
        return load_trainer_data(trainer_data_path)
    return None


def passes_filters(row, filter_names, trainer_data):
    """True if row survives every active named filter (see FILTERS)."""
    return all(FILTERS[name](row, trainer_data) for name in filter_names)
