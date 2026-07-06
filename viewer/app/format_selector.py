"""battleType x curseVariant composite format selector, mirroring the
website's FormatPicker.tsx/formatKey() (web/src/components/FormatPicker.tsx,
web/src/lib/dataClient.ts) -- same two factors, same labels. The website's
selector has a third "filter" factor (cursed_excluded/level70_only), but
those are post-hoc rating-fit filters over results_lib.FILTERS, not
separate raw match sets (results_lib.discover_formats() only ever varies by
battleType x curseVariant) -- Browse/Generate/Watch deal in individual raw
matches, so filter doesn't apply here. General result-list filtering is a
separate future feature, not this composite selector.
"""

BATTLE_TYPES = [("singles", "Singles"), ("doubles", "Doubles")]
CURSE_VARIANTS = [("cursed", "Cursed"), ("uncursed", "Uncursed")]


def format_key(battle_type, curse_variant):
    key = battle_type
    if curse_variant == "uncursed":
        key += "_uncursed"
    return key


def parse_format_key(fmt):
    """Inverse of format_key -- for pre-selecting the two combos from a raw
    format string (e.g. handing off a Browse selection to Generate)."""
    battle_type = "doubles" if "double" in fmt else "singles"
    curse_variant = "uncursed" if "uncursed" in fmt else "cursed"
    return battle_type, curse_variant
