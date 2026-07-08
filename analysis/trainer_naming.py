#!/usr/bin/env python3
"""
Trainer label -> human-readable display name resolution, shared by
trainer_cards.py (PNG cards), export_web_data.py (website JSON), and
viewer/app/trainer_names.py (PySide6 viewer) -- pulled out of trainer_cards.py
so consumers that only need naming (not PIL/resvg_py rendering) can import
this without dragging in image-rendering dependencies.

Pure dict/string logic over trainer_data.json rows (see
results_lib.load_trainer_data) -- no PIL, no filesystem access beyond what the
caller already loaded.
"""


def fight_grouping(card_row, trainer_data_by_label):
    """{version: (fight_number, is_curse_variant)} across every same-identity
    sibling, plus the total distinct-fight count, for the fight-numbering
    scheme shared by distinct_fight_number() and is_curse_variant() below.

    A version with a CURSE_* policy is the same fight as the nearest
    preceding non-cursed version, not a new one (e.g. Yezera's versions
    0/1, 2/3, ... are 6 fights, not 12; Crimson/Teal's identity rotates via
    name_for_hashing rather than real_name, with each identity getting its
    own two fights elsewhere in the version range). Versions with no curse
    at all (e.g. Vanya's 22-version gauntlet) are each their own fight.

    is_curse_variant is only True for a row that got collapsed into an
    earlier sibling's fight number -- never for whichever row started that
    fight number, even if that row's own policies happen to include a
    CURSE_* entry. This matters for Rafael specifically: his version 0 has
    CURSE_FORCE_PERFECT baked into its own PBS entry (always active,
    authored -- not a tournament curse roll), so a naive "has any CURSE_
    policy" check would mark him cursed even though he's every other
    sibling's base fight, indistinguishable from his actual curse-rolled
    version 1 (which adds CURSE_EXTRA_MOVES on top).
    """
    identity = card_row.get("name_for_hashing") or card_row["real_name"]
    siblings = sorted(
        (row for row in trainer_data_by_label.values()
         if row["trainer_type"] == card_row["trainer_type"]
         and (row.get("name_for_hashing") or row["real_name"]) == identity),
        key=lambda row: row["version"],
    )

    grouping = {}
    next_number = 1
    last_base_version = None
    for row in siblings:
        is_cursed = any(p.startswith("CURSE_") for p in row["policies"])
        if is_cursed and last_base_version is not None:
            grouping[row["version"]] = (grouping[last_base_version][0], True)
        else:
            grouping[row["version"]] = (next_number, False)
            next_number += 1
            last_base_version = row["version"]

    return grouping, next_number - 1


def distinct_fight_number(card_row, trainer_data_by_label):
    """1-indexed position of this row's fight among same-identity versions,
    or None if there's only one distinct fight."""
    grouping, total = fight_grouping(card_row, trainer_data_by_label)
    if total <= 1:
        return None
    return grouping[card_row["version"]][0]


def is_curse_variant(card_row, trainer_data_by_label):
    """Whether this row is the curse-rolled instance of its fight, as
    opposed to that fight's base version (see fight_grouping's docstring for
    why this isn't just "has any CURSE_ policy")."""
    grouping, _ = fight_grouping(card_row, trainer_data_by_label)
    return grouping[card_row["version"]][1]


def display_name(card_row, trainer_data_by_label, identities=None):
    """identities, if given, renders as "[real name(s)]" between the real
    name and the "#N" fight-number suffix -- needed when referencing a
    Crimson/Teal masked villain by version number alone (e.g. "Crimson #2")
    would otherwise be ambiguous about which of their several rotating
    identities (see fight_grouping's docstring) that specific version was."""
    display_type = card_row.get("trainer_type_display") or card_row["trainer_type"]
    number = distinct_fight_number(card_row, trainer_data_by_label)
    suffix = f" #{number}" if number is not None else ""
    identity_tag = ""
    if identities:
        names = ", ".join(sorted({i["real_name"] for i in identities}))
        identity_tag = f" [{names}]"
    return f"{display_type} {card_row['real_name']}{identity_tag}{suffix}"


def identity_matches(real_name, trainer_data_by_label):
    """Every non-Masked-Villain trainer_type with this real_name, deduped
    (a name can recur across many versions of the same trainer_type)."""
    by_type = {}
    for row in trainer_data_by_label.values():
        if row["real_name"] != real_name or "MASKEDVILLAIN" in row["trainer_type"]:
            continue
        by_type.setdefault(row["trainer_type"], row)
    return list(by_type.values())


def masked_villain_identities(card_row, trainer_data_by_label):
    """Who's really under the mask, by way of name_for_hashing -- a Masked
    Villain's NameForHashing holds their true identity's real_name (Silver
    is the one exception: MASKEDVILLAIN_Sang has no name_for_hashing at all,
    so it naturally returns nothing). _DOUBLE-class masks are a pair
    fighting together (confirmed: Imogene is currently the only one) so
    every match is shown, not just one; otherwise prefer a plain
    "TRAINER_<name>" match over special variants (confirmed correct for
    Alessa: TRAINER_Alessa over ANOTHERPOSSIBLEALESSA)."""
    trainer_type = card_row["trainer_type"]
    if "MASKEDVILLAIN" not in trainer_type:
        return []
    hashing_name = card_row.get("name_for_hashing")
    if not hashing_name:
        return []
    matches = identity_matches(hashing_name, trainer_data_by_label)
    if not matches:
        return []
    if "_DOUBLE" in trainer_type:
        return matches
    preferred = [r for r in matches if r["trainer_type"].startswith("TRAINER_")]
    return preferred[:1] if preferred else matches[:1]


def safe_filename(label):
    """TYPE:Name#version -> filesystem-safe name, e.g. for output filenames."""
    return label.replace(":", "_").replace("#", "_v")


def resolve_display_name(label, trainer_data_by_label):
    """label ("TYPE:Name#version", matching trainer_data.json's own
    "label" field) -> full display name, doing the masked-villain identity
    lookup and passing it through -- the one call non-rendering consumers
    (viewer, future scripts) actually want, vs. display_name's lower-level
    signature that trainer_cards.py's rendering pipeline calls directly
    because it already has identities computed for other purposes too.

    Appends a plain-text "(Cursed)" marker for a curse-rolled variant --
    trainer_cards.py/the website mark this with a curse-symbol icon instead,
    not practical in a text-only context like the viewer."""
    card_row = trainer_data_by_label[label]
    identities = masked_villain_identities(card_row, trainer_data_by_label)
    name = display_name(card_row, trainer_data_by_label, identities=identities)
    if is_curse_variant(card_row, trainer_data_by_label):
        name += " (Cursed)"
    return name
