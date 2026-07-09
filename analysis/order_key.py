#!/usr/bin/env python3
"""
Canonical trainer1/trainer2 slot order for a pairing -- Python port of
vendor/tectonic-content/Plugins/ELO Tournament/trainer_pool.rb's
canonicalPairOrder, byte-for-byte (both hash the same MD5 digest of the same
sorted-label string and key off the same first-byte parity).

Slot order isn't cosmetic: some battle mechanics (e.g. speed-tie resolution
in pbCalculatePriority) are keyed to battler slot rather than trainer
identity, so which trainer occupies which slot can change a battle's outcome
(see project_trainer_order_dependence memory). Not Python's own hash() --
that's randomized per-process (PYTHONHASHSEED), which would give a different
order every run. MD5 instead, stable across processes/runs/languages.
"""
import hashlib


def canonical_pair_order(label_a, label_b):
    """(first, second) slot order for this pairing, independent of which
    order the caller passes label_a/label_b in."""
    lo, hi = (label_a, label_b) if label_a <= label_b else (label_b, label_a)
    flip = hashlib.md5(f"{lo}|{hi}".encode("utf-8")).digest()[0] % 2 == 0
    return (hi, lo) if flip else (lo, hi)


if __name__ == "__main__":
    # Permanent regression check, not a one-off: symmetry (order doesn't
    # depend on argument order) plus a few fixed vectors -- these need
    # cross-checking against trainer_pool.rb's canonicalPairOrder (same
    # inputs) via the in-engine smoke test, since no standalone `ruby` is
    # available on this machine to script the comparison directly (Tectonic
    # bundles its own Ruby runtime rather than exposing one).
    pairs = [
        ("LEADER_Lambert", "CHALLENGER_Vanya"),
        ("GYMLEADER_Roark", "ACE_TRAINER_Cheryl#2"),
        ("A", "A"),
        ("TRAINER_Zzz", "TRAINER_Aaa"),
    ]
    for a, b in pairs:
        forward = canonical_pair_order(a, b)
        backward = canonical_pair_order(b, a)
        assert forward == backward, f"order({a!r}, {b!r}) depends on argument order: {forward} vs {backward}"
        print(f"{a!r}, {b!r} -> {forward}")

    known_vectors = {
        ("LEADER_Lambert", "CHALLENGER_Vanya"): ("CHALLENGER_Vanya", "LEADER_Lambert"),
    }
    for (a, b), expected in known_vectors.items():
        actual = canonical_pair_order(a, b)
        assert actual == expected, f"order({a!r}, {b!r}) = {actual}, expected {expected}"

    print("order_key self-test passed.")
