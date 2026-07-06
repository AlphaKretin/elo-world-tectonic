#!/usr/bin/env python3
"""
Trainer profile cards: one image per trainer with class/name/version,
rating and W-L-D record (plus a green/yellow/red ratio bar), full party
sprites, curses, and the seed of their best win and worst loss (for
ELO_SAVE_REPLAY) -- in the spirit of elo_world_pokemon_crystal's
trainer_cards, on a bespoke layout rather than the in-game trainer-card
template (too cramped for full sprites and a pixel font at body-text sizes).

Party/policies come from Analysis/trainer_card_data.json, a dump produced
by the game itself (EloTournament.dumpTrainerCardData!, gated by
ELO_DUMP_TRAINER_CARD_DATA) -- not re-derived from PBS here, since
ExtendsVersion inheritance (a versioned trainer's party/policies can pull
in entries from the version it extends) is easy to get subtly wrong outside
the engine's own resolution. Regenerate it with:

    $env:ELO_TOURNAMENT = "1"
    $env:ELO_DUMP_TRAINER_CARD_DATA = "1"
    .\\vendor\\tectonic-content\\Game.exe
(after a debug-mode launch to recompile, if dumpTrainerCardData! itself
just changed.) Wait for Analysis/trainer_card_data.json to appear, then
close Game.exe -- it doesn't exit on its own.

Move type icons are bundled as SVG (vendor/type_icons/, see that
directory's ATTRIBUTION.txt) and rasterized at runtime via resvg_py
(`pip install resvg_py`) -- not cairosvg, which needs a native Cairo DLL
this project doesn't otherwise depend on.

Best win / worst loss come from best_worst_<format>.json (see
best_worst.py); run that (after ratings.py) before this script.
"""
import argparse
import io
import json
import math
import os
from collections import Counter

import resvg_py
from PIL import Image, ImageDraw, ImageFont

from trainer_naming import (
    display_name,
    distinct_fight_number,
    fight_grouping,
    identity_matches,
    is_curse_variant,
    masked_villain_identities,
    safe_filename,
)

import results_lib
from card_constants import TIER_COLORS
from results_lib import ANALYSIS_DIR, CARD_DATA_PATH, REPO_ROOT

RESULTS_DIR = results_lib.RESULTS_DIR
TECTONIC_DIR = os.path.join(REPO_ROOT, "vendor", "tectonic-content")
CARDS_OUT_DIR = os.path.join(ANALYSIS_DIR, "cards")

TRAINER_SPRITE_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Trainers")
FRONT_SPRITE_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Pokemon", "Front")
FRONT_SHINY_SPRITE_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Pokemon", "Front shiny")
ITEM_ICON_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Items")
CURSE_BADGE_PATH = os.path.join(TECTONIC_DIR, "Graphics", "Items", "TAROTAMULET_ACTIVE.png")
TRIBES_PATH = os.path.join(TECTONIC_DIR, "PBS", "tribes.txt")
# The Tribal Bonus Info page's own header icon -- there's no per-tribe icon,
# just this one generic badge for "a tribe bonus is active here".
TRIBE_BADGE_PATH = os.path.join(TECTONIC_DIR, "Graphics", "Pictures", "icon_tribal_bonus.png")
TYPE_ICONS_DIR = os.path.join(REPO_ROOT, "vendor", "type_icons")
# Mutant is a real Tectonic type with its own bundled icon; Flex has no
# dedicated art anywhere (in-game or in this icon set), so -- like the icon
# set's own author did for Mutant -- it borrows the "unknown" glyph.
TYPE_ICON_FALLBACK = "QMarks.svg"
TYPE_ICON_FILES = {
    "NORMAL": "Normal.svg", "FIGHTING": "Fighting.svg", "FLYING": "Flying.svg",
    "POISON": "Poison.svg", "GROUND": "Ground.svg", "ROCK": "Rock.svg",
    "BUG": "Bug.svg", "GHOST": "Ghost.svg", "STEEL": "Steel.svg",
    "FIRE": "Fire.svg", "WATER": "Water.svg", "GRASS": "Grass.svg",
    "ELECTRIC": "Electric.svg", "PSYCHIC": "Psychic.svg", "ICE": "Ice.svg",
    "DRAGON": "Dragon.svg", "DARK": "Dark.svg", "FAIRY": "Fairy.svg",
    "QMARKS": "QMarks.svg", "MUTANT": "Mutant.svg",
}
VENDOR_FONTS_DIR = os.path.join(REPO_ROOT, "vendor", "fonts")
TITLE_FONT_PATH = os.path.join(TECTONIC_DIR, "Fonts", "power clear bold.ttf")  # the game's own pixel font, kept as a deliberate accent for the title only
# Google Fonts (OFL-licensed, see vendor/fonts/OFL-*.txt), bundled rather
# than relying on the game's bundled fonts (legibility at body-text sizes was
# a recurring complaint) or a Windows system font (Segoe UI Symbol has the
# same coverage but isn't ours to redistribute and isn't guaranteed present).
BODY_FONT_PATH = os.path.join(VENDOR_FONTS_DIR, "NotoSans-Regular.ttf")

# Layout is authored in "design space" (a 1100px-wide canvas) and rendered
# at RENDER_SCALE x that for crispness -- same idea as scaling up a small
# native sprite, just for the whole layout instead of a fixed background image.
RENDER_SCALE = 1.6
MARGIN = 36
PORTRAIT_SIZE = 260
GRID_COLUMNS = 3
GRID_GAP = 14
# A nicknamed Pokemon stacks a second line (species+level, then nickname
# below it) inside this same single-line height rather than growing the
# cell -- by design it can overlap into the sprite art below when that
# happens.
CELL_LABEL_HEIGHT = 32
CELL_INNER_PAD = 16
# The label and move grid sit closer to the cell's top/bottom edges than
# CELL_INNER_PAD would put them -- CELL_INNER_PAD itself is left alone since
# it still anchors the sprite's own position (see sprite_area_top in
# render_card), which must not move.
CELL_LABEL_TOP_PAD = 18
MOVE_GRID_TOP_GAP = 10
CELL_BOTTOM_PAD = 16
# Every party sprite is native_size * SPRITE_SCALE, full stop -- no fitting
# a sprite to its cell, no adapting the factor per party. Both of those
# rescale each sprite by a *different* amount depending on its native size
# (or its teammates' sizes), which throws away true relative scale between
# Pokemon: a Diglett would end up bigger than a Wailord if that's what it
# took to fill a box. Cells are sized to fit the single largest sprite in
# the whole roster at this scale -- everything smaller just has more
# breathing room in its cell, which is the correct outcome, not a problem
# to fix by blowing it up.
SPRITE_SCALE = 2
CURSE_BADGE_SIZE = 54
# The tribal-bonus line's own leading icon -- this is the *only* place that
# badge appears now (see TRIBE_BADGE_PATH); it no longer also sits in the
# top-right corner next to the curse badge.
LINE_ICON_SIZE = 30
# Same native/integer-scale reasoning as SPRITE_SCALE -- item icons are pixel
# art too, so this multiplies native icon pixels directly rather than fitting
# to a design-space size (which would scale by a fractional, blurring factor).
ITEM_ICON_SCALE = 2
# Move capsules: a "pill" (radius = half the height) with the type icon
# filling the rounded left end flush (same diameter as the capsule's own
# height, no inset) and the move name filling the rest. Smooth vector art,
# not pixel art -- unlike sprites/items above, these scale and resample
# normally (LANCZOS) rather than by an integer native multiple.
TYPE_ICON_RENDER_SIZE = 128
MOVE_CAPSULE_HEIGHT = 32
MOVE_CAPSULE_GAP = 6
MOVE_CAPSULE_PAD = 6
MOVE_FONT_START = 19
MOVE_FONT_MIN = 13
# Hand-tuned per mask geometry, not a single shared constant -- the single
# mask's one figure sits centered/narrower than the double mask's two, so
# the same offset overshoots on the single case and undershoots on the
# double's gap peek. See identity_offsets() for which applies where.
IDENTITY_OFFSET_SINGLE = 70
IDENTITY_OFFSET_DOUBLE_FAR_RIGHT = 100
IDENTITY_OFFSET_DOUBLE_GAP = -4

COLOR_BG_TOP = (28, 42, 74)
COLOR_BG_BOTTOM = (12, 18, 36)
# A pale tint of the background's own navy hue, not pure white -- reads as
# a cool, slightly frosted panel rather than a glaring cutout.
COLOR_PANEL = (222, 228, 240, 235)
COLOR_CELL = (222, 228, 240, 220)
COLOR_TEXT = (20, 26, 46)
COLOR_DIM = (120, 130, 150)
# Halfway between COLOR_TEXT and COLOR_DIM -- replay seeds need to actually be
# readable (people will be copying them), just not as loud as the result
# they belong to.
COLOR_SEED = (70, 80, 100)
COLOR_WIN = (70, 170, 90)
COLOR_DRAW = (225, 185, 40)
COLOR_LOSS = (195, 60, 50)

TIER_BADGE_HEIGHT = 46  # corner badge diameter


def s(design_px):
    """Scale a design-space pixel value up to the final raster resolution."""
    return round(design_px * RENDER_SCALE)


def load_font(path, design_size):
    return ImageFont.truetype(path, s(design_size))


def fit_font(path, text, max_width, start_size, min_size=12):
    """Largest design-space size (down to min_size) at which text fits max_width."""
    size = start_size
    while size > min_size:
        font = load_font(path, size)
        if font.getlength(text) <= max_width:
            return font
        size -= 1
    return load_font(path, min_size)


def trim_transparent(img):
    """Crop to the opaque bounding box, like elo_world_pokemon_crystal's own
    cropper.py -- sprite canvases have inconsistent padding, which otherwise
    makes same-size art look inconsistently positioned/sized once fitted."""
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def fit_image(img, max_w, max_h):
    scale = min(max_w / img.width, max_h / img.height)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.NEAREST)


def trainer_sprite(trainer_type):
    path = os.path.join(TRAINER_SPRITE_DIR, f"{trainer_type}.png")
    if not os.path.exists(path):
        return None
    return trim_transparent(Image.open(path).convert("RGBA"))


def front_sprite(species, shiny=False):
    """Trainer Pokemon get an authored, bluntly-overridden Shiny=yes/no flag
    (Trainer.rb's pkmn.shiny = ...), not the usual wild-encounter aesthetics-ID
    roll -- so this only needs to pick the matching art file, not decide
    shininess itself. Falls back to the normal sprite if a shiny variant
    doesn't exist on disk for this species, same as the engine's own lookup."""
    if shiny:
        shiny_path = os.path.join(FRONT_SHINY_SPRITE_DIR, f"{species}.png")
        if os.path.exists(shiny_path):
            return trim_transparent(Image.open(shiny_path).convert("RGBA"))
    path = os.path.join(FRONT_SPRITE_DIR, f"{species}.png")
    if not os.path.exists(path):
        return None
    return trim_transparent(Image.open(path).convert("RGBA"))


def item_icon(item_id):
    path = os.path.join(ITEM_ICON_DIR, f"{item_id}.png")
    if not os.path.exists(path):
        return None
    return Image.open(path).convert("RGBA")


def max_native_sprite_dim(card_data_by_label):
    """Largest trimmed-sprite dimension across every species (and shiny/normal
    variant) that appears in any party in the whole roster -- the basis for a
    single fixed grid-cell size, so every card uses the same scale (see
    SPRITE_SCALE)."""
    pairs = {(member["species"], member.get("shiny", False)) for row in card_data_by_label.values() for member in row["party"]}
    best = 0
    for species, shiny in pairs:
        sprite = front_sprite(species, shiny)
        if sprite:
            best = max(best, sprite.width, sprite.height)
    return best


def vertical_gradient(w, h, top, bottom):
    column = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        column.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return column.resize((w, h))


# Hand-tuned, not derived: a single identity peeks right of the mask's own
# edge (the only case so far: Skyler, behind Teal/Crimson's single-figure
# mask). The only double mask (MASKEDVILLAIN_DOUBLE) is two cloaked figures
# side by side with *different* trouser colors -- the left one's trousers
# match Imogene_A's teal dress, the right one's match Imogene_B's green
# dress -- so each Imogene is positioned to peek out near her own color on
# the actual mask sprite, not symmetrically: Imogene_A only needs a small
# rightward nudge into the gap between the two hoods; Imogene_B gets the
# full far-right treatment.
IMOGENE_OFFSETS = {"TRAINER_Imogene_A": IDENTITY_OFFSET_DOUBLE_GAP, "TRAINER_Imogene_B": IDENTITY_OFFSET_DOUBLE_FAR_RIGHT}


def identity_offsets(identities):
    """Design-space x-offset for each identity sprite, paired with the identity."""
    by_type = {i["trainer_type"]: i for i in identities}
    if set(by_type) == set(IMOGENE_OFFSETS):
        return [(by_type[t], offset) for t, offset in IMOGENE_OFFSETS.items()]
    return [(identity, IDENTITY_OFFSET_SINGLE) for identity in identities]


def load_tribe_info():
    """{tribe_id: (threshold, display_name)} from PBS tribes.txt. Unlike
    trainer/species data, tribe definitions are flat with no
    ExtendsVersion-style inheritance, so parsing this directly is safe."""
    info = {}
    with open(TRIBES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tribe_id, threshold, name, _description = line.split(",", 3)
            info[tribe_id] = (int(threshold), name)
    return info


def active_tribe_bonuses(card_row, tribe_info):
    """Tribes whose party-wide member count meets the bonus threshold
    (TribalBonus.rb's updateTribeCount), as (tribe_id, count, threshold,
    name), highest count first."""
    counts = Counter()
    for member in card_row["party"]:
        counts.update(member.get("tribes", []))
    bonuses = []
    for tribe_id, count in counts.items():
        # Tribes outside tribe_info (tribes.txt) are debug/extension-only
        # (e.g. DEBUG_TESTTRIBE, from a test species on some joke/dev
        # trainer's team) -- GameData::Tribe.each_legal excludes these from
        # ever giving a real bonus, so skip them here too.
        if tribe_id not in tribe_info:
            continue
        threshold, name = tribe_info[tribe_id]
        if count >= threshold:
            bonuses.append((tribe_id, count, threshold, name))
    bonuses.sort(key=lambda b: (-b[1], b[3]))
    return bonuses


_type_icon_cache = {}


def load_type_icon(type_id):
    """(icon image, capsule background color) for a move type, rendered
    once from the bundled SVG (vendor/type_icons/, see ATTRIBUTION.txt) and
    cached. The capsule color comes from the icon's own background circle,
    not Tectonic's PBS type Color -- that one's tuned for text on a dark
    background, not a solid fill block, and the two don't always agree
    (e.g. Fire is #F08030 there vs. this icon set's #E4613E)."""
    if type_id in _type_icon_cache:
        return _type_icon_cache[type_id]
    filename = TYPE_ICON_FILES.get(type_id, TYPE_ICON_FALLBACK)
    with open(os.path.join(TYPE_ICONS_DIR, filename), encoding="utf-8") as f:
        svg = f.read()
    png_bytes = resvg_py.svg_to_bytes(svg_string=svg, width=TYPE_ICON_RENDER_SIZE, height=TYPE_ICON_RENDER_SIZE)
    icon = Image.open(io.BytesIO(bytes(png_bytes))).convert("RGBA")
    # A point just inside the left edge, vertically centered -- inside the
    # icon's circular background but clear of every bundled glyph's own
    # extent, verified against all 20 icons.
    bg_color = icon.getpixel((max(2, icon.width // 32), icon.height // 2))[:3]
    _type_icon_cache[type_id] = (icon, bg_color)
    return _type_icon_cache[type_id]


def readable_text_color(bg_color):
    r, g, b = bg_color
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return COLOR_TEXT if luminance > 140 else (255, 255, 255)


def moveset_grid_columns(card_data_by_label, capsule_area_width):
    """2 if the longest move name in the *whole* dataset still fits legibly
    at MOVE_FONT_MIN within a 2-up capsule slice of capsule_area_width,
    else 1 (a column of up to 4) -- decided globally so every card uses the
    same grid shape, rather than each trainer's own moves determining it
    independently (see [[feedback-trainer-card-iteration]] on consistent
    scale being dataset-global, not per-card)."""
    longest = ""
    for row in card_data_by_label.values():
        for member in row["party"]:
            for move in member.get("moves", []):
                if len(move["name"]) > len(longest):
                    longest = move["name"]
    if not longest:
        return 2
    two_up_width = (capsule_area_width - s(MOVE_CAPSULE_GAP)) // 2
    text_budget = two_up_width - s(MOVE_CAPSULE_HEIGHT) - s(MOVE_CAPSULE_PAD) * 2
    floor_font = load_font(BODY_FONT_PATH, MOVE_FONT_MIN)
    return 2 if floor_font.getlength(longest) <= text_budget else 1


def draw_move_capsule(draw, canvas, coords, move):
    x0, y0, x1, y1 = coords
    icon, bg_color = load_type_icon(move["type"])
    draw.rounded_rectangle(coords, radius=(y1 - y0) // 2, fill=bg_color)

    # The icon disc is exactly the capsule's height, flush with its left
    # edge -- it fills the rounded end-cap itself (same bg_color as the
    # icon's own circular background) rather than floating inset with a
    # visible border of capsule color around it.
    icon_size = y1 - y0
    fitted_icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
    icon_pos = (x0, y0)
    canvas.alpha_composite(fitted_icon, icon_pos)

    text_x0 = icon_pos[0] + icon_size + s(MOVE_CAPSULE_PAD)
    text_budget = x1 - text_x0 - s(MOVE_CAPSULE_PAD)
    font = fit_font(BODY_FONT_PATH, move["name"], text_budget, MOVE_FONT_START, min_size=MOVE_FONT_MIN)
    draw.text((text_x0, (y0 + y1) // 2), move["name"], font=font, fill=readable_text_color(bg_color), anchor="lm")


def load_best_worst(fmt):
    """{trainer_label: {"best_win": ..., "worst_loss": ...}} from
    best_worst_<fmt>.json (see best_worst.py -- it computes this in one
    pass over the results instead of trainer_cards.py rescanning them once
    per trainer rendered)."""
    path = os.path.join(ANALYSIS_DIR, f"best_worst_{fmt}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def best_win_tuple(entry):
    """best_worst.json entries are {"opponent", "rating", "seed"} or null;
    render_card wants (rating, opponent, seed) or None."""
    return (entry["rating"], entry["opponent"], entry["seed"]) if entry else None


def draw_wld_bar(draw, coords, wins, losses, draws, min_frac=0.04):
    """Proportional green/yellow/red win-draw-loss bar. Any non-zero category
    is bumped up to min_frac if it would otherwise round away to invisible,
    borrowing space back from the other non-zero categories."""
    total = wins + losses + draws
    if total == 0:
        return
    counts = {"win": wins, "draw": draws, "loss": losses}
    fracs = {k: v / total for k, v in counts.items()}
    nonzero = [k for k in counts if counts[k] > 0]
    deficit = sum(max(0.0, min_frac - fracs[k]) for k in nonzero)
    if deficit > 0:
        donors = [k for k in nonzero if fracs[k] > min_frac]
        donor_total = sum(fracs[k] - min_frac for k in donors) or 1
        for k in nonzero:
            fracs[k] = min_frac if fracs[k] < min_frac else fracs[k] - deficit * (fracs[k] - min_frac) / donor_total

    x0, y0, x1, y1 = coords
    colors = {"win": COLOR_WIN, "draw": COLOR_DRAW, "loss": COLOR_LOSS}
    segments = [k for k in ("win", "draw", "loss") if counts[k] > 0]
    cur = x0
    for i, k in enumerate(segments):
        w = fracs[k] * (x1 - x0)
        is_first, is_last = i == 0, i == len(segments) - 1
        # (top-left, top-right, bottom-right, bottom-left) -- only the outer
        # ends of the whole bar are rounded, so segments butt up against
        # each other with a flat edge instead of each having its own bezel.
        corners = (is_first, is_last, is_last, is_first)
        draw.rounded_rectangle([cur, y0, cur + w, y1], radius=s(6), fill=colors[k], corners=corners)
        cur += w


def render_card(card_row, ratings_row, card_data_by_label, max_native_dim, best_win, worst_loss, out_path):
    margin = s(MARGIN)
    portrait_size = s(PORTRAIT_SIZE)
    gap = s(GRID_GAP)
    inner_pad = s(CELL_INNER_PAD)
    label_h = s(CELL_LABEL_HEIGHT)
    cell_sprite_budget = max_native_dim * SPRITE_SCALE
    cell_w = cell_sprite_budget + 2 * inner_pad
    W = 2 * margin + GRID_COLUMNS * cell_w + (GRID_COLUMNS - 1) * gap

    # Moveset grid: 2-up if the longest move name anywhere in the dataset
    # still fits, else a single column -- same shape on every card (see
    # moveset_grid_columns). Base case reserves 2 or 4 rows; a 5th move
    # (from CURSE_EXTRA_MOVES) expands only the grid rows that need it --
    # all cells in the same card-row equalize to the tallest member's move
    # count so the grid stays rectilinear.
    move_cols = moveset_grid_columns(card_data_by_label, cell_w - 2 * inner_pad)
    base_move_rows = 2 if move_cols == 2 else 4
    capsule_h = s(MOVE_CAPSULE_HEIGHT)
    capsule_gap = s(MOVE_CAPSULE_GAP)
    capsule_w = (cell_w - 2 * inner_pad - (move_cols - 1) * capsule_gap) // move_cols

    def cell_h_for_n_move_rows(n):
        grid_h = n * capsule_h + (n - 1) * capsule_gap
        return inner_pad + label_h + cell_sprite_budget + s(MOVE_GRID_TOP_GAP) + grid_h + s(CELL_BOTTOM_PAD)

    cell_h = cell_h_for_n_move_rows(base_move_rows)

    title_text = display_name(card_row, card_data_by_label)
    text_x = margin + s(24) + portrait_size + s(28)
    text_right = W - margin - s(24)
    tribe_bonuses = active_tribe_bonuses(card_row, load_tribe_info())

    identities = masked_villain_identities(card_row, card_data_by_label)
    # Reserve space for the curse badge at top-right so the title text never
    # extends under it. Computed early (before title font sizing) so the fit
    # uses the real boundary. One badge only -- tribe badge moved to inline.
    is_cursed = any(p.startswith("CURSE_") for p in card_row["policies"])
    badge_right_reserve = s(CURSE_BADGE_SIZE + 12) if is_cursed else 0
    title_font = fit_font(TITLE_FONT_PATH, title_text, text_right - text_x - badge_right_reserve, 50)
    body_font = load_font(BODY_FONT_PATH, 28)
    line_font = load_font(BODY_FONT_PATH, 24)
    seed_font = load_font(BODY_FONT_PATH, 22)

    def opponent_display(label):
        """(name, is_cursed) -- is_cursed reflects the specific opponent
        version this result was recorded against, which curse-deduping can
        hide behind a fight number shared with an uncursed sibling (e.g.
        Bence#2/#3 both display as "Bence #2"; only #3 carries a curse).
        Uses is_curse_variant rather than a raw policy check so a base fight
        with an authored, always-on curse (Rafael's CURSE_FORCE_PERFECT)
        doesn't read as indistinguishable from its actual curse-rolled
        sibling.

        Also passes the opponent's own masked-villain identities (if any)
        through to display_name -- unlike the card's own title (which shows
        identity via the portrait peek + rank-line names instead), a best
        win/worst loss line has no portrait for the opponent, so a Crimson/
        Teal opponent's fight number alone would be ambiguous about which
        rotating identity that particular version was (see display_name)."""
        opp_row = card_data_by_label.get(label)
        if not opp_row:
            return label, False
        opp_identities = masked_villain_identities(opp_row, card_data_by_label)
        name = display_name(opp_row, card_data_by_label, identities=opp_identities)
        return name, is_curse_variant(opp_row, card_data_by_label)

    # Lay out header text top-down, tracking y as we go, so the panel can be
    # sized to fit whatever's actually drawn (an undefeated trainer's header
    # is shorter than a cursed one with both a best win and a worst loss).
    y = margin + s(22)
    title_y = y
    y += s(48)
    rank_y = y
    y += s(TIER_BADGE_HEIGHT) + s(8)
    record_y = y
    y += s(34)
    bar_y = y
    y += s(30)

    lines = []  # (prefix, icon_path_or_None, suffix, seed_or_None)
    if tribe_bonuses:
        # The tribal-bonus badge icon itself (TRIBE_BADGE_PATH) leads the
        # line in place of a "Tribal Bonus:" label -- it's the one icon for
        # "a tribe bonus is active here", so it doesn't need a text header
        # alongside it, just the active tribes' own names.
        names = [name for _, _, _, name in tribe_bonuses]
        lines.append(("", TRIBE_BADGE_PATH, ', '.join(names), None))
    if best_win:
        rating, opponent, seed = best_win
        opp_text, opp_cursed = opponent_display(opponent)
        icon = CURSE_BADGE_PATH if opp_cursed else None
        lines.append(("Best win: ", icon, f"{opp_text} ({rating:.0f})", seed))
    else:
        lines.append(("Best win: --", None, "", None))
    if worst_loss:
        rating, opponent, seed = worst_loss
        opp_text, opp_cursed = opponent_display(opponent)
        icon = CURSE_BADGE_PATH if opp_cursed else None
        lines.append(("Worst loss: ", icon, f"{opp_text} ({rating:.0f})", seed))
    else:
        lines.append(("Worst loss: --", None, "", None))

    line_ys = []
    for _, _, _, seed in lines:
        line_ys.append(y)
        y += s(36) if seed else 0
        y += s(28)

    # Identity reveals are layered behind the portrait itself now (see below),
    # not a separate row, so they no longer affect header height at all.
    left_column_bottom = margin + s(22) + portrait_size + s(14)
    header_bottom = max(y + s(10), left_column_bottom)

    party = card_row["party"]
    grid_rows = math.ceil(len(party) / GRID_COLUMNS) if party else 0
    grid_top = header_bottom + s(22)

    # Per-card-row cell heights: all cells in a row share the height needed
    # for whichever member has the most moves in that row.
    row_heights = []
    for gr in range(grid_rows):
        row_members = [party[gr * GRID_COLUMNS + c] for c in range(GRID_COLUMNS)
                       if gr * GRID_COLUMNS + c < len(party)]
        max_moves = max((len(m.get("moves") or []) for m in row_members), default=0)
        n = max(base_move_rows, math.ceil(max_moves / move_cols)) if max_moves else base_move_rows
        row_heights.append(cell_h_for_n_move_rows(n))
    row_tops = [grid_top + sum(row_heights[:gr]) + gr * gap for gr in range(grid_rows)]

    H = (grid_top + sum(row_heights) + max(0, grid_rows - 1) * gap + margin) if grid_rows else header_bottom + margin

    canvas = vertical_gradient(W, H, COLOR_BG_TOP, COLOR_BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle((margin, margin, W - margin, header_bottom), radius=s(26), fill=COLOR_PANEL)

    portrait_box = (margin + s(24), margin + s(22), margin + s(24) + portrait_size, margin + s(22) + portrait_size)
    box_w, box_h = portrait_box[2] - portrait_box[0], portrait_box[3] - portrait_box[1]
    # An offset identity peek must never bleed into the text column to its
    # right or spill past the panel's own left edge -- clip to a viewport
    # that stops just short of the text and starts at the panel margin.
    peek_clip = (margin, portrait_box[1], text_x - s(14), portrait_box[3])

    def paste_in_portrait_box(sprite_img, x_offset=0, clip=None):
        fitted = fit_image(sprite_img, box_w, box_h)
        pos = (portrait_box[0] + x_offset + (box_w - fitted.width) // 2,
               portrait_box[1] + (box_h - fitted.height) // 2)
        if clip:
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            layer.alpha_composite(fitted, pos)
            cx0, cy0, cx1, cy1 = clip
            canvas.alpha_composite(layer.crop((cx0, cy0, cx1, cy1)), (cx0, cy0))
        else:
            canvas.alpha_composite(fitted, pos)

    # Who's really under the mask is layered behind the mask itself, offset
    # sideways, instead of a separate row of labeled thumbnails -- a peek
    # rather than a caption, and it no longer touches the header's height.
    for identity, offset_design in identity_offsets(identities):
        identity_sprite = trainer_sprite(identity["trainer_type"])
        if identity_sprite:
            paste_in_portrait_box(identity_sprite, x_offset=s(offset_design), clip=peek_clip)

    sprite = trainer_sprite(card_row["trainer_type"])
    if sprite:
        paste_in_portrait_box(sprite)

    tier = ratings_row.get("tier")
    if tier and tier in TIER_COLORS:
        badge_color = TIER_COLORS[tier]
        tdiam = s(TIER_BADGE_HEIGHT)
        tx0, ty0 = margin + s(10), margin + s(10)
        draw.ellipse((tx0, ty0, tx0 + tdiam, ty0 + tdiam), fill=badge_color)
        tier_font = load_font(BODY_FONT_PATH, 24)
        draw.text((tx0 + tdiam // 2, ty0 + tdiam // 2), tier, font=tier_font,
                   fill=readable_text_color(badge_color), anchor="mm")

    draw.text((text_x, title_y), title_text, font=title_font, fill=COLOR_TEXT)

    rank_text = f"#{ratings_row['rank']} overall · {ratings_row['rating']:.1f} Elo"
    true_names = sorted({i["real_name"] for i in identities})
    if true_names:
        rank_text += f" · ({', '.join(true_names)})"
    rank_font = fit_font(TITLE_FONT_PATH, rank_text, text_right - text_x, 30, min_size=14)

    row_center_y = rank_y + s(TIER_BADGE_HEIGHT) // 2
    draw.text((text_x, row_center_y), rank_text, font=rank_font, fill=COLOR_DIM, anchor="lm")
    record = f"{ratings_row['wins']}W - {ratings_row['draws']}D - {ratings_row['losses']}L   ({ratings_row['battles']} battles)"
    draw.text((text_x, record_y), record, font=body_font, fill=COLOR_TEXT)
    draw_wld_bar(draw, (text_x, bar_y, text_right, bar_y + s(22)), ratings_row["wins"], ratings_row["losses"], ratings_row["draws"])

    badge_paths = []
    if is_cursed and os.path.exists(CURSE_BADGE_PATH):
        badge_paths.append(CURSE_BADGE_PATH)
    badge_x = text_right
    for badge_path in badge_paths:
        badge = fit_image(Image.open(badge_path).convert("RGBA"), s(CURSE_BADGE_SIZE), s(CURSE_BADGE_SIZE))
        badge_x -= badge.width
        canvas.alpha_composite(badge, (badge_x, margin + s(14)))
        badge_x -= s(8)

    for (prefix, icon_path, suffix, seed), ly in zip(lines, line_ys):
        cur_x = text_x
        if prefix:
            draw.text((cur_x, ly), prefix, font=line_font, fill=COLOR_TEXT)
            cur_x += line_font.getlength(prefix)
        suffix_y, anchor = ly, None
        if icon_path and os.path.exists(icon_path):
            icon_size = s(LINE_ICON_SIZE)
            icon_img = fit_image(trim_transparent(Image.open(icon_path).convert("RGBA")), icon_size, icon_size)
            icon_y = ly + (line_font.size - icon_img.height) // 2
            canvas.alpha_composite(icon_img, (round(cur_x), icon_y))
            # Cropping the icon to its bounding box removes its own baked-in
            # padding, so the text needs a smaller gap than an uncropped icon
            # would to still read as evenly kerned against it.
            cur_x += icon_img.width + s(4)
            suffix_y = icon_y + icon_img.height / 2
            anchor = "lm"
        if suffix:
            # Unlike the title/rank lines above (fit_font against text_right
            # from the start), these lines were never width-checked -- fine
            # while every suffix was short, but a masked-villain identity
            # bracket (opponent_display) can push one past the panel's right
            # edge, so shrink to fit the same way those lines already do.
            suffix_font = fit_font(BODY_FONT_PATH, suffix, text_right - cur_x, 24, min_size=14)
            draw.text((cur_x, suffix_y), suffix, font=suffix_font, fill=COLOR_TEXT, anchor=anchor)
        if seed:
            draw.text((text_x, ly + s(30)), f"Seed: {seed}", font=seed_font, fill=COLOR_SEED)

    for i, member in enumerate(party):
        col, gr = i % GRID_COLUMNS, i // GRID_COLUMNS
        cx0 = margin + col * (cell_w + gap)
        cy0 = row_tops[gr]
        ch = row_heights[gr]
        draw.rounded_rectangle((cx0, cy0, cx0 + cell_w, cy0 + ch), radius=s(18), fill=COLOR_CELL)

        species_display = member.get("species_display") or member["species"].title()
        species_line = f"{species_display}  Lv.{member['level']}"
        label_max_w = cell_w - 2 * inner_pad
        label_cx, label_cy = cx0 + cell_w // 2, cy0 + s(CELL_LABEL_TOP_PAD)
        nickname = member.get("nickname")
        if nickname:
            # species+level stays exactly where it always sits (same as the
            # non-nicknamed case below); the nickname stacks below it,
            # pushing down into the sprite art below. Accepted tradeoff, not
            # a bug to fix -- both lines equally weighted, not one dimmed.
            nick_font = fit_font(BODY_FONT_PATH, nickname, label_max_w, 24, min_size=14)
            species_font = fit_font(BODY_FONT_PATH, species_line, label_max_w, 24, min_size=14)
            draw.text((label_cx, label_cy + s(26)), nickname, font=nick_font, fill=COLOR_TEXT, anchor="mm")
            draw.text((label_cx, label_cy), species_line, font=species_font, fill=COLOR_TEXT, anchor="mm")
        else:
            species_font = fit_font(BODY_FONT_PATH, species_line, label_max_w, 24, min_size=14)
            draw.text((label_cx, label_cy), species_line, font=species_font, fill=COLOR_TEXT, anchor="mm")

        sprite_area_top = cy0 + inner_pad + label_h
        sprite = front_sprite(member["species"], member.get("shiny", False))
        if sprite:
            scaled = sprite.resize((sprite.width * SPRITE_SCALE, sprite.height * SPRITE_SCALE), Image.NEAREST)
            pos = (cx0 + inner_pad + (cell_sprite_budget - scaled.width) // 2,
                   sprite_area_top + (cell_sprite_budget - scaled.height) // 2)
            canvas.alpha_composite(scaled, pos)
        # Held-item icon(s) sit in the same fixed corner of the sprite-area
        # box on every cell, regardless of that particular sprite's size --
        # anchoring to each sprite's own bounding box instead made the icon
        # clip past the box for sprites that nearly fill the budget (e.g.
        # Rafael's Yveltal), and put it in a different-looking spot on every
        # card besides.
        corner_x = cx0 + inner_pad + cell_sprite_budget - inner_pad
        corner_y = sprite_area_top + cell_sprite_budget - inner_pad
        for n, item in enumerate(member.get("held_items") or []):
            icon = item_icon(item["id"])
            if not icon:
                continue
            fitted = icon.resize((icon.width * ITEM_ICON_SCALE, icon.height * ITEM_ICON_SCALE), Image.NEAREST)
            pos = (corner_x - fitted.width - n * fitted.width, corner_y - fitted.height)
            canvas.alpha_composite(fitted, pos)

        move_grid_top = sprite_area_top + cell_sprite_budget + s(MOVE_GRID_TOP_GAP)
        for mi, move in enumerate(member.get("moves") or []):
            mcol, mrow = mi % move_cols, mi // move_cols
            mx0 = cx0 + inner_pad + mcol * (capsule_w + capsule_gap)
            my0 = move_grid_top + mrow * (capsule_h + capsule_gap)
            draw_move_capsule(draw, canvas, (mx0, my0, mx0 + capsule_w, my0 + capsule_h), move)

    canvas.convert("RGB").save(out_path)


# Canonical regression set -- covers every distinct rendering path this
# script has grown, so a layout/data change can be checked against all of
# them in one pass instead of whatever one-off trainer happened to be handy.
# Re-run with --test-cases after any change. (Picked against the live,
# post-reset results; re-pick a replacement if one ever drops out of the
# pool, e.g. a quarantined policy.)
TEST_CASES = [
    ("ANOTHERPOSSIBLERAFAEL:Rafael#1", "undefeated #1, CURSE_EXTRA_MOVES -- all 6 Pokemon have 5 moves (5th-move grid expansion), large legendary sprites, male; best win is against base Rafael (v0), whose authored CURSE_FORCE_PERFECT must NOT show the inline curse badge (see is_curse_variant)"),
    ("MASKEDVILLAIN2:Teal#5", "cursed with both a win and a loss, single identity reveal (Skyler)"),
    ("HEXMANIAC:Errata", "non-cursed, female, species display-name fixes (H. Electrode, Farfetch'd), single tribal bonus"),
    ("YOUNGSTER:Joey", "1-Pokemon party (grid edge case), worst record in the pool"),
    ("MASKEDVILLAIN:Crimson#2", "single identity reveal, ambiguous match resolved to TRAINER_Alessa"),
    ("MASKEDVILLAIN_DOUBLE:Crimson", "double identity reveal (Imogene A & B), \"Masked Villains\" plural title"),
    ("MASKEDVILLAIN_Sang:Silver", "no identity reveal shown (MASKEDVILLAIN_Sang has no name_for_hashing)"),
    ("MASKEDVILLAIN_Sang:Silver#1", "cursed AND tribal bonus together -- both corner badges stacked, no overlap"),
    ("BATTLEGIRL:Tester", "3 simultaneous tribal bonuses (comma-joined line, no overflow); also a 6x-identical-species party"),
    ("GAMBLER:Tiki", "has the longest move name in the dataset (Dielectric Breakdown) -- the case that decides moveset_grid_columns() globally"),
    ("POKEMONMASTER_Vanya:Vanya#12", "22-version sequence; fight number always shown since every version is a distinct fight"),
    ("LEADER_Eko:Eko", "gym leader with a bad record"),
    ("LEADER_Helena:Helena#2", "wins + losses + draws all present -- full 3-color WLD bar"),
    ("LEADER_Noel:Noel", "nicknamed + shiny party member (Armiger the Metagross), authored override not the wild aesthetics-ID roll"),
    ("SPIRITGUARDIAN4:Brigitte#1", "worst loss recorded against a genuinely curse-rolled opponent version (SEEKER_Nora:Nora#1) -- curse badge shown inline on the Worst loss line; best-win badge cases are already covered elsewhere in this set"),
    ("ANOTHERPOSSIBLEALESSA:Alessa#1", "best win and worst loss both against masked villains (Teal#15, Crimson#11) -- both lines must show the identity bracket (opponent_display), not just the fight number, since neither opponent's own portrait is on this card"),
]


def render_one(label, fmt, ratings_by_label, card_data_by_label, best_worst_by_label, max_native_dim):
    if label not in ratings_by_label:
        raise KeyError(f"No ratings entry for trainer {label!r}.")
    if label not in card_data_by_label:
        raise KeyError(f"No trainer_card_data.json entry for trainer {label!r}.")
    if label not in best_worst_by_label:
        raise KeyError(f"No best_worst_{fmt}.json entry for trainer {label!r} -- re-run best_worst.py.")
    bw = best_worst_by_label[label]
    best_win, worst_loss = best_win_tuple(bw["best_win"]), best_win_tuple(bw["worst_loss"])
    os.makedirs(CARDS_OUT_DIR, exist_ok=True)
    out_path = os.path.join(CARDS_OUT_DIR, f"{safe_filename(label)}.png")
    render_card(card_data_by_label[label], ratings_by_label[label], card_data_by_label, max_native_dim, best_win, worst_loss, out_path)
    return out_path


def main():
    global RESULTS_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", default=None, help="Format to use (default: singles, or the first format found if singles isn't present)")
    parser.add_argument("--trainer", default=None, help="Trainer label, e.g. 'MASKEDVILLAIN2:Teal#5' (default: #1 ranked)")
    parser.add_argument("--test-cases", action="store_true", help="Render the whole canonical TEST_CASES set instead of a single trainer")
    parser.add_argument(
        "--results-dir", default=RESULTS_DIR, metavar="DIR",
        help="Directory containing elo_results_*_shard*.jsonl files (default: results/remote/; use results/ for local shard data)",
    )
    args = parser.parse_args()
    RESULTS_DIR = args.results_dir

    if not os.path.exists(CARD_DATA_PATH):
        raise SystemExit(
            f"{CARD_DATA_PATH} not found -- run the ELO_DUMP_TRAINER_CARD_DATA dump first (see this script's docstring)."
        )

    found_formats = results_lib.discover_formats(RESULTS_DIR)
    fmt = args.format or ("singles" if "singles" in found_formats else found_formats[0])
    ratings_by_label = results_lib.load_ratings(fmt, analysis_dir=ANALYSIS_DIR)
    card_data_by_label = results_lib.load_card_data()
    best_worst_path = os.path.join(ANALYSIS_DIR, f"best_worst_{fmt}.json")
    if not os.path.exists(best_worst_path):
        raise SystemExit(f"{best_worst_path} not found -- run `python analysis/best_worst.py --format {fmt}` first.")
    best_worst_by_label = load_best_worst(fmt)
    max_native_dim = max_native_sprite_dim(card_data_by_label)

    if args.test_cases:
        for label, why in TEST_CASES:
            try:
                out_path = render_one(label, fmt, ratings_by_label, card_data_by_label, best_worst_by_label, max_native_dim)
                print(f"Wrote {out_path}  ({why})")
            except KeyError as e:
                print(f"SKIPPED {label!r} ({why}): {e}")
        return

    label = args.trainer or next(iter(ratings_by_label))  # ratings_<fmt>.json is rank-sorted
    out_path = render_one(label, fmt, ratings_by_label, card_data_by_label, best_worst_by_label, max_native_dim)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
