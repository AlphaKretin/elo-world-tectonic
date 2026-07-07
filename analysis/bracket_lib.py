#!/usr/bin/env python3
"""
Shared logic for the viewer's Bracket tab: building a 16-entrant seeded
single-elimination tree, resolving matches by looking them up in existing
round-robin results (or a previously-generated bracket sidecar) before ever
falling back to running a fresh headless battle, and deriving reproducible
RNG seeds for that fallback case.

Deliberately independent of vendor/tectonic-content/Plugins/ELO Tournament/
bracket.rb -- the viewer never shells out to bracket.rb/run_bracket.ps1, it
re-derives the same standard bracket shape and resolves matches client-side
in Python instead (see project plan discussion). The seed ordering below is
ported from bracket.rb's SEED_ORDER_16 constant (a verified-correct standard
16-team single-elimination seeding, not re-derived algorithmically here, to
avoid subtly diverging from that convention).
"""
import hashlib
import re

import results_lib

_SLUG_RE = re.compile(r"^bracket_(?P<fmt>.+)_r(?P<round>\d+)m(?P<match>\d+)_rank")

# Standard 16-slot single-elimination seeding order (NCAA-style: 1v16, 8v9,
# 5v12, 4v13, 3v14, 6v11, 7v10, 2v15) -- keeps the top seeds apart for as
# long as possible. Pairing consecutive slots each round and advancing the
# winner into the same slot naturally reproduces the full bracket without
# needing to special-case later rounds. Ported from bracket.rb's
# SEED_ORDER_16 rather than re-derived, since it's already a verified-correct
# standard order.
SEED_ORDER_16 = [1, 16, 8, 9, 5, 12, 4, 13, 3, 14, 6, 11, 7, 10, 2, 15]
ROUND_NAMES = ["Round of 16", "Quarterfinals", "Semifinals", "Final"]


class Match:
    """One bracket match. `rank_a`/`rank_b`/`label_a`/`label_b` are `None`
    until both parent matches (or, for round 0, the curated seed list) have
    resolved. `winner_label`/`winner_rank` are `None` until this match is
    itself resolved."""

    def __init__(self, round_idx, match_idx):
        self.round_idx = round_idx
        self.match_idx = match_idx
        self.rank_a = None
        self.label_a = None
        self.rank_b = None
        self.label_b = None
        self.winner_label = None
        self.winner_rank = None
        self.resolved_seed = None  # RNG seed that decided this match, kept even after
        # resolution so a later on-demand replay generation (e.g. Watch after Skip)
        # can reproduce the same outcome without re-deriving a seed.

    @property
    def resolved(self):
        return self.winner_label is not None

    @property
    def ready(self):
        """Both entrants known, not yet resolved."""
        return not self.resolved and self.label_a is not None and self.label_b is not None


def build_bracket_tree(labels):
    """labels: the 16 curated trainer labels in seed order (labels[0] is
    seed 1, labels[15] is seed 16). Returns a list of rounds, each a list of
    Match objects; round 0's matches are pre-filled from the seed list,
    later rounds start with both slots empty until their parent matches
    resolve (see advance_winner)."""
    if len(labels) != 16:
        raise ValueError(f"Need exactly 16 curated labels, got {len(labels)}")

    by_rank = {rank: label for rank, label in zip(range(1, 17), labels)}
    round0_labels = [by_rank[rank] for rank in SEED_ORDER_16]
    round0_ranks = SEED_ORDER_16

    rounds = []
    round0 = []
    for match_idx in range(8):
        m = Match(0, match_idx)
        m.rank_a, m.rank_b = round0_ranks[2 * match_idx], round0_ranks[2 * match_idx + 1]
        m.label_a, m.label_b = round0_labels[2 * match_idx], round0_labels[2 * match_idx + 1]
        round0.append(m)
    rounds.append(round0)

    match_count = 4
    for round_idx in range(1, 4):
        rounds.append([Match(round_idx, i) for i in range(match_count)])
        match_count //= 2

    return rounds


def advance_winner(rounds, round_idx, match_idx, winner_label, winner_rank):
    """Records match (round_idx, match_idx)'s winner and, if there's a next
    round, fills in the appropriate slot of its parent match."""
    match = rounds[round_idx][match_idx]
    match.winner_label = winner_label
    match.winner_rank = winner_rank

    if round_idx + 1 >= len(rounds):
        return
    parent = rounds[round_idx + 1][match_idx // 2]
    if match_idx % 2 == 0:
        parent.label_a, parent.rank_a = winner_label, winner_rank
    else:
        parent.label_b, parent.rank_b = winner_label, winner_rank


def build_results_index(rows):
    """{frozenset({trainer1, trainer2}): [rows]} over a format's round-robin
    rows, for O(1) pairing lookup regardless of which trainer ended up in
    which of the jsonl's trainer1/trainer2 slots."""
    index = {}
    for row in rows:
        key = frozenset({row["trainer1"], row["trainer2"]})
        index.setdefault(key, []).append(row)
    return index


def lookup_result(results_index, label_a, label_b):
    """First decisive (non-draw) row for this pairing, if any. Draws are
    skipped rather than treated as resolving the match -- a drawn RR sample
    doesn't tell us who'd actually win a decisive bracket match."""
    for row in results_index.get(frozenset({label_a, label_b}), []):
        if row.get("result") in (results_lib.WIN, results_lib.LOSS):
            return row
    return None


def _stable_hash(*parts):
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def derive_fresh_seed(fmt, round_idx, match_idx, label_a, label_b):
    """Deterministic first-attempt RNG seed for a pairing the round robin
    never covered, so re-opening the same bracket reproduces the same
    fresh-generated outcome. Independent of bracket.rb's own seed
    derivation -- this is an unrelated resolution path."""
    return _stable_hash("bracket", fmt, round_idx, match_idx, label_a, label_b)


def next_retry_seed(previous_seed):
    """Deterministic seed for a manual retry after a draw, chained off the
    *actual* previous seed rather than re-derived from the match's static
    position -- otherwise two different bracket contexts that both drew on
    their first attempt would always converge on the same next seed too."""
    return _stable_hash("bracket-retry", previous_seed)


def bracket_replay_slug(fmt, round_idx, match_idx, rank_a, label_a, rank_b, label_b, attempt=0):
    """Filename (sans extension) for a bracket match's replay .dat, mirroring
    bracket.rb's bracketReplaySlug naming convention."""
    def slugify(label):
        return "".join(c if c.isalnum() or c in "_.-" else "_" for c in label)

    slug = (
        f"bracket_{fmt}_r{round_idx + 1}m{match_idx + 1}"
        f"_rank{rank_a}-{slugify(label_a)}_vs_rank{rank_b}-{slugify(label_b)}"
    )
    if attempt:
        slug += f"_attempt{attempt}"
    return slug


def parse_bracket_slug(name):
    """Reverses bracket_replay_slug's naming enough to identify which match
    a saved replay belongs to: (fmt, round_idx, match_idx), or None if name
    doesn't look like a bracket replay at all. Used to map a just-watched
    replay back to its match without the viewer needing to track "which
    match is pending watch" as separate in-memory state."""
    m = _SLUG_RE.match(name)
    if not m:
        return None
    return m.group("fmt"), int(m.group("round")) - 1, int(m.group("match")) - 1
