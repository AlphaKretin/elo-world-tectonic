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
"""
import argparse
import glob
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
TECTONIC_DIR = os.path.join(REPO_ROOT, "vendor", "tectonic-content")
CARD_DATA_PATH = os.path.join(TECTONIC_DIR, "Analysis", "trainer_card_data.json")
CARDS_OUT_DIR = os.path.join(ANALYSIS_DIR, "cards")

TRAINER_SPRITE_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Trainers")
FRONT_SPRITE_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Pokemon", "Front")
FRONT_SHINY_SPRITE_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Pokemon", "Front shiny")
ITEM_ICON_DIR = os.path.join(TECTONIC_DIR, "Graphics", "Items")
CURSE_BADGE_PATH = os.path.join(TECTONIC_DIR, "Graphics", "Items", "TAROTAMULET_ACTIVE.png")
VENDOR_FONTS_DIR = os.path.join(REPO_ROOT, "vendor", "fonts")
TITLE_FONT_PATH = os.path.join(TECTONIC_DIR, "Fonts", "power clear bold.ttf")  # the game's own pixel font, kept as a deliberate accent for the title only
# Google Fonts (OFL-licensed, see vendor/fonts/OFL-*.txt), bundled rather
# than relying on the game's bundled fonts (no ⚥/⚧ coverage; legibility at
# body-text sizes was a recurring complaint) or a Windows system font
# (Segoe UI Symbol has all of these glyphs too, but isn't ours to redistribute
# and isn't guaranteed present on every machine).
BODY_FONT_PATH = os.path.join(VENDOR_FONTS_DIR, "NotoSans-Regular.ttf")
SYMBOL_FONT_PATH = os.path.join(VENDOR_FONTS_DIR, "NotoSansSymbols-Regular.ttf")

WIN, LOSS, DRAW = 1, 2, 5

# Layout is authored in "design space" (a 1100px-wide canvas) and rendered
# at RENDER_SCALE x that for crispness -- same idea as scaling up a small
# native sprite, just for the whole layout instead of a fixed background image.
RENDER_SCALE = 1.6
MARGIN = 36
PORTRAIT_SIZE = 260
GRID_COLUMNS = 3
GRID_GAP = 14
# A nicknamed Pokemon stacks a second line (nickname above species+level)
# inside this same single-line height rather than growing the cell -- by
# design it can overlap into the sprite art above when that happens.
CELL_LABEL_HEIGHT = 32
CELL_INNER_PAD = 16
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
# Same native/integer-scale reasoning as SPRITE_SCALE -- item icons are pixel
# art too, so this multiplies native icon pixels directly rather than fitting
# to a design-space size (which would scale by a fractional, blurring factor).
ITEM_ICON_SCALE = 2
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
COLOR_GENDER_MALE = (70, 120, 220)
COLOR_GENDER_FEMALE = (220, 70, 90)
COLOR_GENDER_OTHER = (155, 80, 210)

# TrainerType gender: 0=Male, 1=Female, 2=Unknown/Mixed, 3=Wild. 2 covers
# both genuinely unknown (e.g. Masked Villains, gender-ambiguous by design)
# and real affirmatively non-binary characters, so it gets its own glyph
# rather than being skipped -- only Wild (not really a "gender" in the
# representational sense) shows nothing.
GENDER_GLYPHS = {0: ("♂", COLOR_GENDER_MALE), 1: ("♀", COLOR_GENDER_FEMALE), 2: ("⚥", COLOR_GENDER_OTHER)}


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


def display_name(card_row):
    display_type = card_row.get("trainer_type_display") or card_row["trainer_type"]
    return f"{display_type} {card_row['real_name']} #{card_row['version'] + 1}"


def identity_matches(real_name, card_data_by_label):
    """Every non-Masked-Villain trainer_type with this real_name, deduped
    (a name can recur across many versions of the same trainer_type)."""
    by_type = {}
    for row in card_data_by_label.values():
        if row["real_name"] != real_name or "MASKEDVILLAIN" in row["trainer_type"]:
            continue
        by_type.setdefault(row["trainer_type"], row)
    return list(by_type.values())


# Silver's mask doesn't hide much -- his trainer_type is literally
# MASKEDVILLAIN_Sang, spelling out his real identity directly instead of
# routing it through NameForHashing like the other Masked Villains. Not
# shown as an identity-reveal (he's not really a "who's under the mask?"
# the way the others are) but still worth resolving for his gender.
SILVER_TRAINER_TYPE = "MASKEDVILLAIN_Sang"
SILVER_TRUE_NAME = "Sang"


def masked_villain_identities(card_row, card_data_by_label):
    """Who's really under the mask, by way of name_for_hashing -- a Masked
    Villain's NameForHashing holds their true identity's real_name (Silver
    is the one exception: no name_for_hashing at all, so naturally returns
    nothing -- see SILVER_TRAINER_TYPE). _DOUBLE-class masks are a pair
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
    matches = identity_matches(hashing_name, card_data_by_label)
    if not matches:
        return []
    if "_DOUBLE" in trainer_type:
        return matches
    preferred = [r for r in matches if r["trainer_type"].startswith("TRAINER_")]
    return preferred[:1] if preferred else matches[:1]


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


def resolved_gender(card_row, identities, card_data_by_label):
    """The mask's own TrainerType is gender Unknown/Mixed by design (it's a
    disguise) -- if there's exactly one identity behind it (or several
    agreeing, e.g. both Imogenes), show *their* gender instead of the
    mask's. Silver has no NameForHashing identity to fall back to via
    `identities` (see SILVER_TRAINER_TYPE), so he gets his own lookup."""
    gender = card_row.get("gender")
    if gender != 2:
        return gender
    candidates = identities
    if not candidates and card_row["trainer_type"] == SILVER_TRAINER_TYPE:
        candidates = identity_matches(SILVER_TRUE_NAME, card_data_by_label)
    identity_genders = {r.get("gender") for r in candidates if r.get("gender") is not None}
    return next(iter(identity_genders)) if len(identity_genders) == 1 else gender


def discover_formats():
    formats = set()
    for path in glob.glob(os.path.join(RESULTS_DIR, "elo_results_*_shard*.jsonl")):
        name = os.path.basename(path)
        middle = name[len("elo_results_"):-len(".jsonl")]
        formats.add(middle.rsplit("_shard", 1)[0])
    return sorted(formats)


def load_ratings(fmt):
    path = os.path.join(ANALYSIS_DIR, f"ratings_{fmt}.json")
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["trainer"]: row for row in rows}


def load_card_data():
    with open(CARD_DATA_PATH, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["label"]: row for row in rows}


def best_and_worst(fmt, label, ratings_by_label):
    """Highest-rated trainer beaten, and lowest-rated trainer lost to, with seeds."""
    best_win = None    # (opponent_rating, opponent_label, seed)
    worst_loss = None  # (opponent_rating, opponent_label, seed)
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, f"elo_results_{fmt}_shard*.jsonl"))):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("skipped") or row.get("had_error"):
                    continue
                t1, t2, result = row.get("trainer1"), row.get("trainer2"), row.get("result")
                if label not in (t1, t2) or result not in (WIN, LOSS):
                    continue
                opponent = t2 if label == t1 else t1
                won = (result == WIN) == (label == t1)
                opp_rating = ratings_by_label.get(opponent, {}).get("rating")
                if opp_rating is None:
                    continue
                if won:
                    if best_win is None or opp_rating > best_win[0]:
                        best_win = (opp_rating, opponent, row.get("seed"))
                else:
                    if worst_loss is None or opp_rating < worst_loss[0]:
                        worst_loss = (opp_rating, opponent, row.get("seed"))
    return best_win, worst_loss


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
    cell_h = cell_sprite_budget + label_h + 2 * inner_pad
    W = 2 * margin + GRID_COLUMNS * cell_w + (GRID_COLUMNS - 1) * gap

    title_text = display_name(card_row)
    text_x = margin + s(24) + portrait_size + s(28)
    text_right = W - margin - s(24)

    identities = masked_villain_identities(card_row, card_data_by_label)
    gender = resolved_gender(card_row, identities, card_data_by_label)
    glyph, glyph_color = GENDER_GLYPHS.get(gender, (None, None))
    glyph_reserve = s(50) if glyph else 0
    title_font = fit_font(TITLE_FONT_PATH, title_text, text_right - text_x - glyph_reserve, 50)
    body_font = load_font(BODY_FONT_PATH, 28)
    line_font = load_font(BODY_FONT_PATH, 24)
    seed_font = load_font(BODY_FONT_PATH, 22)

    def opponent_display(label):
        opp_row = card_data_by_label.get(label)
        return display_name(opp_row) if opp_row else label

    # Lay out header text top-down, tracking y as we go, so the panel can be
    # sized to fit whatever's actually drawn (an undefeated trainer's header
    # is shorter than a cursed one with both a best win and a worst loss).
    y = margin + s(22)
    title_y = y
    y += s(48)
    rank_y = y
    y += s(38)
    record_y = y
    y += s(34)
    bar_y = y
    y += s(30)

    lines = []  # (main_text, seed_or_None)
    if best_win:
        rating, opponent, seed = best_win
        lines.append((f"Best win: {opponent_display(opponent)} ({rating:.0f})", seed))
    else:
        lines.append(("Best win: --", None))
    if worst_loss:
        rating, opponent, seed = worst_loss
        lines.append((f"Worst loss: {opponent_display(opponent)} ({rating:.0f})", seed))
    else:
        lines.append(("Worst loss: --", None))

    line_ys = []
    for _, seed in lines:
        line_ys.append(y)
        y += s(36) if seed else 0
        y += s(28)

    # Identity reveals are layered behind the portrait itself now (see below),
    # not a separate row, so they no longer affect header height at all.
    left_column_bottom = margin + s(22) + portrait_size + s(14)
    header_bottom = max(y + s(10), left_column_bottom)

    party = card_row["party"]
    rows = math.ceil(len(party) / GRID_COLUMNS) if party else 0
    grid_top = header_bottom + s(22)
    H = grid_top + rows * cell_h + max(0, rows - 1) * gap + margin if rows else header_bottom + margin

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

    draw.text((text_x, title_y), title_text, font=title_font, fill=COLOR_TEXT)
    if glyph:
        glyph_font = load_font(SYMBOL_FONT_PATH, title_font.size / RENDER_SCALE)
        gx = text_x + title_font.getlength(title_text) + s(10)
        gy = title_y + title_font.size * 0.55
        draw.text((gx, gy), glyph, font=glyph_font, fill=glyph_color, anchor="lm")
    rank_text = f"#{ratings_row['rank']} overall · {ratings_row['rating']:.1f} Elo"
    true_names = sorted({i["real_name"] for i in identities})
    if true_names:
        rank_text += f" · ({', '.join(true_names)})"
    rank_font = fit_font(TITLE_FONT_PATH, rank_text, text_right - text_x, 30, min_size=14)
    draw.text((text_x, rank_y), rank_text, font=rank_font, fill=COLOR_DIM)
    record = f"{ratings_row['wins']}W - {ratings_row['draws']}D - {ratings_row['losses']}L   ({ratings_row['battles']} battles)"
    draw.text((text_x, record_y), record, font=body_font, fill=COLOR_TEXT)
    draw_wld_bar(draw, (text_x, bar_y, text_right, bar_y + s(22)), ratings_row["wins"], ratings_row["losses"], ratings_row["draws"])

    is_cursed = any(p.startswith("CURSE_") for p in card_row["policies"])
    if is_cursed and os.path.exists(CURSE_BADGE_PATH):
        badge = fit_image(Image.open(CURSE_BADGE_PATH).convert("RGBA"), s(CURSE_BADGE_SIZE), s(CURSE_BADGE_SIZE))
        canvas.alpha_composite(badge, (text_right - badge.width, margin + s(14)))

    for (main_text, seed), ly in zip(lines, line_ys):
        draw.text((text_x, ly), main_text, font=line_font, fill=COLOR_TEXT)
        if seed:
            draw.text((text_x, ly + s(30)), f"Seed: {seed}", font=seed_font, fill=COLOR_SEED)

    for i, member in enumerate(party):
        col, row = i % GRID_COLUMNS, i // GRID_COLUMNS
        cx0 = margin + col * (cell_w + gap)
        cy0 = grid_top + row * (cell_h + gap)
        draw.rounded_rectangle((cx0, cy0, cx0 + cell_w, cy0 + cell_h), radius=s(18), fill=COLOR_CELL)
        sprite_area_top = cy0 + inner_pad
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
        for n, item_id in enumerate(member.get("held_items") or []):
            icon = item_icon(item_id)
            if not icon:
                continue
            fitted = icon.resize((icon.width * ITEM_ICON_SCALE, icon.height * ITEM_ICON_SCALE), Image.NEAREST)
            pos = (corner_x - fitted.width - n * fitted.width, corner_y - fitted.height)
            canvas.alpha_composite(fitted, pos)
        species_display = member.get("species_display") or member["species"].title()
        species_line = f"{species_display}  Lv.{member['level']}"
        label_max_w = cell_w - 2 * inner_pad
        label_cx, label_cy = cx0 + cell_w // 2, cy0 + cell_h - label_h // 2
        nickname = member.get("nickname")
        if nickname:
            # species+level stays exactly where it always sits (same as the
            # non-nicknamed case below); the nickname stacks above it,
            # pushing up into the sprite art above. Accepted tradeoff, not
            # a bug to fix -- both lines equally weighted, not one dimmed.
            nick_font = fit_font(BODY_FONT_PATH, nickname, label_max_w, 24, min_size=14)
            species_font = fit_font(BODY_FONT_PATH, species_line, label_max_w, 24, min_size=14)
            draw.text((label_cx, label_cy - s(26)), nickname, font=nick_font, fill=COLOR_TEXT, anchor="mm")
            draw.text((label_cx, label_cy), species_line, font=species_font, fill=COLOR_TEXT, anchor="mm")
        else:
            species_font = fit_font(BODY_FONT_PATH, species_line, label_max_w, 24, min_size=14)
            draw.text((label_cx, label_cy), species_line, font=species_font, fill=COLOR_TEXT, anchor="mm")

    canvas.convert("RGB").save(out_path)


def safe_filename(label):
    return label.replace(":", "_").replace("#", "_v")


# Canonical regression set -- covers every distinct rendering path this
# script has grown, so a layout/data change can be checked against all of
# them in one pass instead of whatever one-off trainer happened to be handy.
# Re-run with --test-cases after any change. (Picked against the live,
# post-reset results; re-pick a replacement if one ever drops out of the
# pool, e.g. a quarantined policy.)
TEST_CASES = [
    ("ANOTHERPOSSIBLERAFAEL:Rafael#1", "undefeated #1, cursed, full team of large legendary sprites, male"),
    ("MASKEDVILLAIN2:Teal#5", "cursed with both a win and a loss, single identity reveal + gender fallback (Skyler)"),
    ("HEXMANIAC:Errata", "non-cursed, female, species display-name fixes (H. Electrode, Farfetch'd)"),
    ("YOUNGSTER:Joey", "1-Pokemon party (grid edge case), worst record in the pool"),
    ("MASKEDVILLAIN:Crimson#2", "single identity reveal, ambiguous match resolved to TRAINER_Alessa"),
    ("MASKEDVILLAIN_DOUBLE:Crimson", "double identity reveal (Imogene A & B), \"Masked Villains\" plural title"),
    ("MASKEDVILLAIN_Sang:Silver", "no identity reveal shown, gender still resolved via the Sang fallback"),
    ("POKEMONMASTER_Vanya:Vanya#12", "genuine non-binary gender (consistent across all her versions)"),
    ("LEADER_Eko:Eko", "non-binary gender after the trainertypes.txt data fix, bad record"),
    ("LEADER_Helena:Helena#2", "wins + losses + draws all present -- full 3-color WLD bar"),
    ("LEADER_Noel:Noel", "nicknamed + shiny party member (Armiger the Metagross), authored override not the wild aesthetics-ID roll"),
]


def render_one(label, fmt, ratings_by_label, card_data_by_label, max_native_dim):
    if label not in ratings_by_label:
        raise KeyError(f"No ratings entry for trainer {label!r}.")
    if label not in card_data_by_label:
        raise KeyError(f"No trainer_card_data.json entry for trainer {label!r}.")
    best_win, worst_loss = best_and_worst(fmt, label, ratings_by_label)
    os.makedirs(CARDS_OUT_DIR, exist_ok=True)
    out_path = os.path.join(CARDS_OUT_DIR, f"{safe_filename(label)}.png")
    render_card(card_data_by_label[label], ratings_by_label[label], card_data_by_label, max_native_dim, best_win, worst_loss, out_path)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", default=None, help="Format to use (default: first one found)")
    parser.add_argument("--trainer", default=None, help="Trainer label, e.g. 'MASKEDVILLAIN2:Teal#5' (default: #1 ranked)")
    parser.add_argument("--test-cases", action="store_true", help="Render the whole canonical TEST_CASES set instead of a single trainer")
    args = parser.parse_args()

    if not os.path.exists(CARD_DATA_PATH):
        raise SystemExit(
            f"{CARD_DATA_PATH} not found -- run the ELO_DUMP_TRAINER_CARD_DATA dump first (see this script's docstring)."
        )

    fmt = args.format or discover_formats()[0]
    ratings_by_label = load_ratings(fmt)
    card_data_by_label = load_card_data()
    max_native_dim = max_native_sprite_dim(card_data_by_label)

    if args.test_cases:
        for label, why in TEST_CASES:
            try:
                out_path = render_one(label, fmt, ratings_by_label, card_data_by_label, max_native_dim)
                print(f"Wrote {out_path}  ({why})")
            except KeyError as e:
                print(f"SKIPPED {label!r} ({why}): {e}")
        return

    label = args.trainer or next(iter(ratings_by_label))  # ratings_<fmt>.json is rank-sorted
    out_path = render_one(label, fmt, ratings_by_label, card_data_by_label, max_native_dim)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
