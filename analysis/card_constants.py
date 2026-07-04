"""Shared constants between trainer_cards.py (PIL renderer) and
export_web_data.py (the website's data export) -- kept in one place so the
two renderers can't silently drift apart on tier/type colors.

TYPE_COLORS was computed once by sampling each bundled type icon's own
background-circle pixel (see trainer_cards.py's load_type_icon) -- baked
here as a static dict rather than re-sampled at runtime by both consumers,
since the source SVGs never change. Re-run the sampling loop in
load_type_icon's docstring if a type icon is ever swapped out.
"""

# Same low (F) -> high (S+) ramp elo_world_pokemon_red's own tier_colors
# uses -- a "heat" gradient (green -> yellow -> orange -> red -> magenta),
# not red=bad/green=good, matching common tier-list convention.
TIER_COLORS = {
    "F": (0, 176, 80), "D-": (36, 187, 69), "D": (75, 199, 53), "D+": (111, 210, 38),
    "C-": (147, 222, 21), "C": (184, 233, 0), "C+": (220, 244, 0), "B-": (255, 255, 0),
    "B": (255, 214, 0), "B+": (255, 172, 0), "A-": (255, 93, 0), "A": (255, 87, 0),
    "A+": (255, 43, 0), "S": (255, 0, 0), "S+": (255, 0, 80),
}

# bg_color sampled from each type icon's own circular background (see
# trainer_cards.py's load_type_icon docstring for why this isn't PBS's type
# Color) -- QMARKS is also Mutant... no, Mutant has its own icon; QMARKS is
# the fallback used for any type without a dedicated icon file at all.
TYPE_COLORS = {
    "NORMAL": (130, 130, 130), "FIGHTING": (228, 144, 33), "FLYING": (116, 170, 208),
    "POISON": (147, 84, 203), "GROUND": (164, 115, 60), "ROCK": (169, 164, 129),
    "BUG": (159, 159, 40), "GHOST": (111, 69, 112), "STEEL": (119, 178, 203),
    "FIRE": (228, 97, 62), "WATER": (48, 153, 225), "GRASS": (67, 152, 55),
    "ELECTRIC": (223, 188, 40), "PSYCHIC": (233, 108, 140), "ICE": (71, 200, 200),
    "DRAGON": (87, 111, 188), "DARK": (79, 71, 71), "FAIRY": (225, 140, 225),
    "QMARKS": (68, 68, 68), "MUTANT": (162, 114, 146),
}


def readable_text_color(bg_color):
    r, g, b = bg_color
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (20, 26, 46) if luminance > 140 else (255, 255, 255)
