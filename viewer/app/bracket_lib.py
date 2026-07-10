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

import order_key
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
    resolved. A match is a series of attempts, each either a draw or
    decisive; `winner_label`/`winner_rank` stay `None` until one side's
    decisive-attempt count reaches `wins_needed`."""

    def __init__(self, round_idx, match_idx, wins_needed=2):
        self.round_idx = round_idx
        self.match_idx = match_idx
        self.rank_a = None
        self.label_a = None
        self.rank_b = None
        self.label_b = None
        self.wins_needed = wins_needed
        self.attempts = []  # ordered list of {"seed": int, "winner_label": str | None}; None = draw
        self.winner_label = None
        self.winner_rank = None
        # The seed for the currently-pending attempt -- what Watch/Skip/
        # Generate act on right now. None until both entrants are known
        # (see bracket_tab.py's _ensure_match_seed); user-editable/rerollable
        # from there on, and advanced by bracket_tab.py after each recorded
        # attempt (a draw, or a decisive-but-not-yet-final game).
        self.seed = None

    @property
    def current_attempt_idx(self):
        """Index (0-based) of the attempt about to be played next -- also
        the `attempt` value to pass to bracket_replay_slug for it."""
        return len(self.attempts)

    @property
    def decisive_attempts(self):
        return [a for a in self.attempts if a["winner_label"] is not None]

    @property
    def wins_a(self):
        return sum(1 for a in self.decisive_attempts if a["winner_label"] == self.label_a)

    @property
    def wins_b(self):
        return sum(1 for a in self.decisive_attempts if a["winner_label"] == self.label_b)

    @property
    def draws(self):
        return sum(1 for a in self.attempts if a["winner_label"] is None)

    @property
    def score_text(self):
        """"wins_a-wins_b", plus a third "-draws" component only when a
        draw has actually happened -- otherwise a draws=0 suffix would show
        on every match regardless, when in practice it's rare."""
        base = f"{self.wins_a}-{self.wins_b}"
        return f"{base}-{self.draws}" if self.draws else base

    @property
    def resolved(self):
        return self.winner_label is not None

    @property
    def ready(self):
        """Both entrants known, not yet resolved."""
        return not self.resolved and self.label_a is not None and self.label_b is not None


def record_attempt(match, winner_label, winner_rank, seed):
    """Appends one played attempt to `match.attempts` (`winner_label=None`
    for a draw -- draws still consume an attempt slot, since the next
    attempt's seed chains off *this* attempt's actual seed regardless of
    whether it was decisive, and the replay filename numbering needs every
    attempt counted). If this decisive result brings a side's win count up
    to `match.wins_needed`, sets `match.winner_label`/`winner_rank`. Returns
    whether the match is now resolved -- callers still call advance_winner
    themselves when true, since this function doesn't touch `rounds`."""
    match.attempts.append({"seed": seed, "winner_label": winner_label})
    if winner_label is None:
        return False
    wins = match.wins_a if winner_label == match.label_a else match.wins_b
    if wins >= match.wins_needed:
        match.winner_label = winner_label
        match.winner_rank = winner_rank
        return True
    return False


def build_bracket_tree(labels, wins_needed=2):
    """labels: the 16 curated trainer labels in seed order (labels[0] is
    seed 1, labels[15] is seed 16). Returns a list of rounds, each a list of
    Match objects; round 0's matches are pre-filled from the seed list,
    later rounds start with both slots empty until their parent matches
    resolve (see advance_winner). wins_needed (default 2, i.e. best-of-3) is
    the number of decisive attempts a side needs to take any match in the
    tree; 1 reproduces a plain single-game bracket."""
    if len(labels) != 16:
        raise ValueError(f"Need exactly 16 curated labels, got {len(labels)}")

    by_rank = {rank: label for rank, label in zip(range(1, 17), labels)}
    round0_labels = [by_rank[rank] for rank in SEED_ORDER_16]
    round0_ranks = SEED_ORDER_16

    rounds = []
    round0 = []
    for match_idx in range(8):
        m = Match(0, match_idx, wins_needed=wins_needed)
        m.rank_a, m.rank_b = round0_ranks[2 * match_idx], round0_ranks[2 * match_idx + 1]
        m.label_a, m.label_b = round0_labels[2 * match_idx], round0_labels[2 * match_idx + 1]
        round0.append(m)
    rounds.append(round0)

    match_count = 4
    for round_idx in range(1, 4):
        rounds.append([Match(round_idx, i, wins_needed=wins_needed) for i in range(match_count)])
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


def pick_default_row(results_index, label_a, label_b):
    """Any existing row (round-robin or a previously-generated/merged
    sidecar) for this pairing, preferring a decisive one over a draw, or
    None. Used only to choose a match's *initial* seed (so a bracket
    reproduces the known result by default) -- never for deciding whether
    Watch/Generate should be offered, which is exact-seed matching via
    find_row_for_seed instead."""
    rows = results_index.get(frozenset({label_a, label_b}), [])
    for row in rows:
        if row.get("result") in (results_lib.WIN, results_lib.LOSS):
            return row
    return rows[0] if rows else None


def find_row_for_seed(results_index, label_a, label_b, seed):
    """The row (if any) for this pairing whose seed exactly matches --
    round-robin and locally-generated results share one index (see
    BracketTab._merge_cached_sidecars), so this is the single source of
    truth for whether *this specific* seed has already been played,
    regardless of where that result came from. A rerolled seed that's never
    been played simply has no matching row here, distinct from -- not
    shadowed by -- any other seed's row for the same pairing."""
    for row in results_index.get(frozenset({label_a, label_b}), []):
        if row.get("seed") == seed:
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


def next_attempt_seed(previous_seed):
    """Deterministic seed for the next attempt in a match's sequence,
    chained off the *actual* previous attempt's seed rather than re-derived
    from the match's static position -- otherwise two different bracket
    contexts whose first attempt happened to share a result would always
    converge on the same next seed too.

    Used for every non-initial attempt uniformly: a draw being retried and
    a decisive-but-not-yet-final game advancing to the next one are the same
    kind of step in the chain (e.g. Win -> Draw -> Loss -> Win is a valid
    attempt sequence) -- there is deliberately no separate seed function for
    "next game" versus "retry after a draw"."""
    return _stable_hash("bracket-retry", previous_seed)


def bracket_replay_slug(fmt, round_idx, match_idx, rank_a, label_a, rank_b, label_b, seed):
    """Filename (sans extension) for a bracket match's replay .dat, mirroring
    bracket.rb's bracketReplaySlug naming convention (with a seed suffix
    bracket.rb doesn't have -- see find_row_for_seed's docstring for why: it
    makes every distinct seed's replay for this same match position get its
    own file automatically, so a rerolled-and-regenerated attempt never
    collides with or overwrites an earlier one; best-of-N retries already
    get distinct seeds via next_attempt_seed chaining, so they get distinct
    filenames the same way, with no separate attempt counter needed)."""
    def slugify(label):
        return "".join(c if c.isalnum() or c in "_.-" else "_" for c in label)

    return (
        f"bracket_{fmt}_r{round_idx + 1}m{match_idx + 1}"
        f"_rank{rank_a}-{slugify(label_a)}_vs_rank{rank_b}-{slugify(label_b)}_seed{seed}"
    )


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
