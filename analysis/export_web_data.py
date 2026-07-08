#!/usr/bin/env python3
"""
Export analysis/*.json (ratings, best_worst, trainer_card_data) into the
web/ frontend's public/data/<format>/ directory, plus the referenced subset
of sprites/icons/fonts into web/public/assets/ -- feeds the website's live
HTML trainer card component, which supersedes trainer_cards.py's PIL PNGs
as the public-facing rendering (this script and that one share layout
constants/logic via card_constants.py and direct imports, so they can't
silently drift apart on tier/type colors or the fight-grouping/dataset-wide
decisions).

Regenerates ratings_<fmt>.json and best_worst_<fmt>.json for every
FORMAT_SPEC itself before exporting (see regenerate_analysis_outputs) --
this used to be a manual "run ratings.py and best_worst.py first" step,
which is exactly how the site ended up shipping a stale
best_worst_singles.json/best_worst_doubles.json on 2026-07-04: an
errored-battle rerun updated the base formats' results, ratings.py got
rerun to match, but best_worst.py didn't, and nothing caught the gap
before the site was exported. Regenerating both here, every time, means
there's no manual step left to forget. Skips any FORMAT_SPEC with no
usable results yet rather than failing the whole run.
"""
import json
import os
import shutil

import best_worst
import ratings
import results_lib
import trainer_cards
from card_constants import TIER_COLORS
from results_lib import REPO_ROOT

def build_format_specs(card_data):
    """(base format, filters) pairs to publish -- base format is either a
    real elo_results_<fmt>_shard*.jsonl dataset (singles/doubles/*_uncursed)
    or, combined with filters, a post-hoc row-filtered view of one (see
    results_lib.FILTERS). cursed_excluded is never crossed with an _uncursed
    base (it's a row-level curse-drop, not a fixed trainer cohort, so
    there's no population to check). Every filter in
    results_lib.FILTER_TRAINER_PREDICATES DOES have a fixed cohort, so it's
    only crossed with an _uncursed base if that cohort actually contains a
    cursed trainer (see results_lib.filter_has_cursed_population) --
    otherwise the _uncursed variant would just be a byte-identical copy of
    the plain cursed default, and the website falls back cursed instead of
    publishing the duplicate (see web/src/lib/formatValidity.ts)."""
    specs = [
        ("singles", []), ("doubles", []),
        ("singles_uncursed", []), ("doubles_uncursed", []),
        ("singles", ["cursed_excluded"]), ("doubles", ["cursed_excluded"]),
    ]
    for filt in sorted(results_lib.FILTER_TRAINER_PREDICATES):
        specs.append(("singles", [filt]))
        specs.append(("doubles", [filt]))
        if results_lib.filter_has_cursed_population(filt, card_data):
            specs.append(("singles_uncursed", [filt]))
            specs.append(("doubles_uncursed", [filt]))
    return specs

WEB_DIR = os.path.join(REPO_ROOT, "web")
WEB_DATA_DIR = os.path.join(WEB_DIR, "public", "data")
WEB_ASSETS_DIR = os.path.join(WEB_DIR, "public", "assets")


def wld_fractions(wins, losses, draws, min_frac=0.04):
    """Port of trainer_cards.draw_wld_bar's fraction math only (no drawing)
    -- {win,draw,loss: 0..1}, post min-visible-fraction adjustment."""
    total = wins + losses + draws
    if total == 0:
        return {"win": 0.0, "draw": 0.0, "loss": 0.0}
    counts = {"win": wins, "draw": draws, "loss": losses}
    fracs = {k: v / total for k, v in counts.items()}
    nonzero = [k for k in counts if counts[k] > 0]
    deficit = sum(max(0.0, min_frac - fracs[k]) for k in nonzero)
    if deficit > 0:
        donors = [k for k in nonzero if fracs[k] > min_frac]
        donor_total = sum(fracs[k] - min_frac for k in donors) or 1
        for k in nonzero:
            fracs[k] = (
                min_frac if fracs[k] < min_frac
                else fracs[k] - deficit * (fracs[k] - min_frac) / donor_total
            )
    return fracs


def opponent_payload(label, card_data_by_label):
    opp_row = card_data_by_label.get(label)
    if not opp_row:
        return {"label": label, "display": label, "cursed": False}
    opp_identities = trainer_cards.masked_villain_identities(opp_row, card_data_by_label)
    name = trainer_cards.display_name(opp_row, card_data_by_label, identities=opp_identities)
    cursed = trainer_cards.is_curse_variant(opp_row, card_data_by_label)
    return {"label": label, "display": name, "cursed": cursed}


def best_worst_payload(entry, card_data_by_label, ratings_by_label):
    if not entry:
        return None
    opponent_row = ratings_by_label.get(entry["opponent"])
    return {
        "rating": entry["rating"],
        "seed": entry["seed"],
        "opponent": opponent_payload(entry["opponent"], card_data_by_label),
        # Opponent's own rank in this same format's leaderboard, alongside
        # the rating they had at fight time (entry["rating"]) -- None only
        # if the opponent somehow isn't in this format's fit at all, which
        # shouldn't happen since best/worst is computed from the same
        # format's battles.
        "opponentRank": opponent_row["rank"] if opponent_row else None,
    }


def static_trainer_payload(label, card_data_by_label, tribe_info):
    """Everything about a trainer that does NOT vary by format (identity,
    party, curse-authoring, tribe bonuses) -- written once to
    web/public/data/trainers/, not duplicated per format. Rank/rating/
    record/best-worst DO vary by format and live in each format's own
    leaderboard.json row instead (see leaderboard_row below)."""
    row = card_data_by_label[label]
    identities = trainer_cards.masked_villain_identities(row, card_data_by_label)
    tribe_bonuses = trainer_cards.active_tribe_bonuses(row, tribe_info)
    is_cursed = results_lib.is_cursed_trainer(label, card_data_by_label)
    levels = [m["level"] for m in row["party"]]
    return {
        "label": label,
        "title": trainer_cards.display_name(row, card_data_by_label),
        "trainerType": row["trainer_type"],
        "identities": [
            {"trainerType": i["trainer_type"], "realName": i["real_name"]}
            for i in identities
        ],
        "trueNames": sorted({i["real_name"] for i in identities}),
        "isCursed": is_cursed,
        "tribeBonuses": [
            {"tribeId": t, "count": c, "threshold": th, "name": n}
            for t, c, th, n in tribe_bonuses
        ],
        # Team level is format-independent (party doesn't vary by
        # battleType/curseVariant, see the module docstring), so it's stored
        # once here rather than per-format -- also mirrored into the
        # standalone team_levels.json summary (see export_team_levels) so
        # the Stats page can plot it against every format's ratings without
        # fetching every trainer's static payload individually.
        "avgLevel": sum(levels) / len(levels) if levels else 0,
        "maxLevel": max(levels) if levels else 0,
        "party": [
            {
                "species": m["species"],
                "speciesDisplay": m.get("species_display") or m["species"].title(),
                "level": m["level"],
                "shiny": m.get("shiny", False),
                "nickname": m.get("nickname"),
                "tribes": m.get("tribes", []),
                "heldItems": m.get("held_items") or [],
                "moves": m.get("moves") or [],
            }
            for m in row["party"]
        ],
    }


def export_trainers(card_data_by_label, tribe_info, formats):
    """Every trainer referenced by ANY format's ratings gets exactly one
    static payload file, regardless of how many formats it appears in."""
    out_dir = os.path.join(WEB_DATA_DIR, "trainers")
    os.makedirs(out_dir, exist_ok=True)
    referenced = set()
    for fmt in formats:
        ratings_path = os.path.join(results_lib.RATINGS_DIR, f"ratings_{fmt}.json")
        if os.path.exists(ratings_path):
            referenced |= set(results_lib.load_ratings(fmt))
    n = 0
    for label in referenced:
        if label not in card_data_by_label:
            continue
        payload = static_trainer_payload(label, card_data_by_label, tribe_info)
        out_path = os.path.join(out_dir, f"{trainer_cards.safe_filename(label)}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
        n += 1
    print(f"trainers: {n} static payloads -> {out_dir}")


def export_team_levels(card_data_by_label):
    """Standalone label -> {avgLevel, maxLevel} summary for every trainer,
    format-independent (see static_trainer_payload). Lets the Stats page
    plot team level against any format's ratings with one fetch instead of
    one fetch per trainer (there's no per-format subset filtering here --
    every trainer with a party gets an entry, same set the trainers/
    directory covers)."""
    out = {}
    for label, row in card_data_by_label.items():
        levels = [m["level"] for m in row["party"]]
        if not levels:
            continue
        out[label] = {
            "avgLevel": sum(levels) / len(levels),
            "maxLevel": max(levels),
        }
    with open(os.path.join(WEB_DATA_DIR, "team_levels.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=4)
    print(f"team_levels: {len(out)} entries -> {WEB_DATA_DIR}")


def export_format(fmt, card_data_by_label):
    """Per-format leaderboard.json: everything that DOES vary by format
    (rank, rating, record, tier, best win/worst loss), keyed by the same
    label the static trainers/<label>.json uses."""
    ratings_by_label = results_lib.load_ratings(fmt)
    best_worst_by_label = trainer_cards.load_best_worst(fmt)

    out_dir = os.path.join(WEB_DATA_DIR, fmt)
    os.makedirs(out_dir, exist_ok=True)

    leaderboard = []
    for label, row in ratings_by_label.items():
        if label not in card_data_by_label:
            continue
        bw = best_worst_by_label.get(label, {})
        tier = row.get("tier")
        leaderboard.append({
            "label": label,
            # Reuses opponent_payload's display name so a masked villain's
            # own leaderboard row shows their true identity the same way it
            # already does when they appear as someone else's best-win/
            # worst-loss opponent -- row["trainer"] from ratings.json has
            # no identity tag, only the plain trainer_type + real_name.
            "trainer": opponent_payload(label, card_data_by_label)["display"],
            # Same fight-grouping distinction opponent lines already use --
            # a curse-deduped display name can hide a base/cursed sibling
            # pair behind the same "#N" number, so the leaderboard needs its
            # own per-row cursed flag (distinct from the trainer's own
            # authored-curse isCursed field in trainers/<label>.json).
            "cursed": trainer_cards.is_curse_variant(card_data_by_label[label], card_data_by_label),
            "rating": row["rating"], "se": row["se"],
            "ciLow": row["ci_low"], "ciHigh": row["ci_high"],
            "wins": row["wins"], "losses": row["losses"], "draws": row["draws"],
            "battles": row["battles"], "rank": row["rank"],
            "overlap": row.get("overlap"), "tier": tier,
            "tierColor": TIER_COLORS.get(tier),
            "wldFractions": wld_fractions(row["wins"], row["losses"], row["draws"]),
            "bestWin": best_worst_payload(bw.get("best_win"), card_data_by_label, ratings_by_label),
            "worstLoss": best_worst_payload(bw.get("worst_loss"), card_data_by_label, ratings_by_label),
        })
    leaderboard.sort(key=lambda r: r["rank"])
    with open(os.path.join(out_dir, "leaderboard.json"), "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=4)

    print(f"{fmt}: {len(leaderboard)} leaderboard rows -> {out_dir}")


def _copy_if_exists(src, dst):
    if src and os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


def export_assets(card_data_by_label):
    """Copy only the LOCAL-only assets: shiny Pokemon sprites (Luna's own
    tectonic-tools/Sirv CDN doesn't host shiny sprites -- confirmed by
    checking that repo directly), our own type-icon SVGs, fonts, and badge
    icons. Non-shiny Pokemon/Trainer/Item sprites are hotlinked from
    tectonic-tools' Sirv CDN instead (see web/src/lib/dataClient.ts's
    REMOTE_SPRITE_ROOT) -- Luna owns that repo and CDN, so there's no
    hotlinking-etiquette concern, and it avoids committing ~1200 sprite
    files/~10MB of largely-duplicate binary assets to this repo."""
    species_shiny_pairs = {
        (m["species"], True)
        for row in card_data_by_label.values()
        for m in row["party"]
        if m.get("shiny", False)
    }

    n = 0
    for species, _shiny in species_shiny_pairs:
        src = os.path.join(trainer_cards.FRONT_SHINY_SPRITE_DIR, f"{species}.png")
        n += _copy_if_exists(src, os.path.join(WEB_ASSETS_DIR, "pokemon_shiny", f"{species}.png"))

    # Curse badge (TAROTAMULET_ACTIVE) is hotlinked from tectonic-tools'
    # Items/ CDN path instead (see web/src/components/RemoteSprite.tsx) --
    # only the tribal-bonus badge stays local, since it's a UI icon
    # (Graphics/Pictures) rather than a game item, and isn't hosted there.
    n += _copy_if_exists(trainer_cards.TRIBE_BADGE_PATH, os.path.join(WEB_ASSETS_DIR, "badges", "tribe.png"))

    for type_id, filename in trainer_cards.TYPE_ICON_FILES.items():
        src = os.path.join(trainer_cards.TYPE_ICONS_DIR, filename)
        n += _copy_if_exists(src, os.path.join(WEB_ASSETS_DIR, "types", filename))
    _copy_if_exists(
        os.path.join(trainer_cards.TYPE_ICONS_DIR, trainer_cards.TYPE_ICON_FALLBACK),
        os.path.join(WEB_ASSETS_DIR, "types", trainer_cards.TYPE_ICON_FALLBACK),
    )

    _copy_if_exists(trainer_cards.TITLE_FONT_PATH, os.path.join(WEB_ASSETS_DIR, "fonts", "power-clear-bold.ttf"))
    _copy_if_exists(trainer_cards.BODY_FONT_PATH, os.path.join(WEB_ASSETS_DIR, "fonts", "NotoSans-Regular.ttf"))

    print(f"assets: copied {n} sprite/icon files -> {WEB_ASSETS_DIR}")


def _write_ratings(base_fmt, filters, leaderboard, stats):
    fmt = base_fmt + results_lib.filter_suffix(filters)
    if not leaderboard:
        print(f"SKIPPED regen for {fmt}: no usable results yet")
        return
    suffix = results_lib.filter_suffix(filters)
    ratings.write_outputs(base_fmt, leaderboard, suffix=suffix)
    ratings_by_label = {row["trainer"]: row for row in leaderboard}
    best_win, worst_loss = best_worst.compute_best_worst(base_fmt, ratings_by_label, filters=filters)
    best_worst.write_output(base_fmt, suffix, best_win, worst_loss, ratings_by_label.keys())
    total_battles = sum(s["battles"] for s in stats.values()) // 2
    print(f"regenerated {fmt}: {len(leaderboard)} trainers, {total_battles} battles")


def regenerate_analysis_outputs(format_specs):
    """Recompute ratings_<fmt>.json and best_worst_<fmt>.json for every
    format_specs entry (see build_format_specs) from the current
    results/current data, so this script is the one place that has to be run
    for the site to be fresh -- see the module docstring for why relying on
    ratings.py/best_worst.py having already been run by hand isn't good
    enough.

    Every (base, filters) spec whose (base + '_uncursed', filters)
    counterpart is also in format_specs gets fit as an anchored pair
    (ratings.compute_anchored_uncursed_pair) instead of two independent
    zero-anchored fits -- see that function's docstring for why. Anything
    without a matching uncursed counterpart (cursed_excluded, which is
    never crossed with an _uncursed base -- see build_format_specs -- or a
    filter cohort with no cursed trainers) falls back to the standalone
    fit, unchanged from before."""
    spec_set = {(base, tuple(filters)) for base, filters in format_specs}
    processed = set()

    for base_fmt, filters in format_specs:
        key = (base_fmt, tuple(filters))
        if key in processed:
            continue

        if not results_lib.is_uncursed_format(base_fmt):
            uncursed_fmt = base_fmt + results_lib.UNCURSED_SUFFIX
            uncursed_key = (uncursed_fmt, tuple(filters))
            if uncursed_key in spec_set:
                pair = ratings.compute_anchored_uncursed_pair(base_fmt, filters=filters)
                if pair is not None:
                    base_leaderboard, uncursed_leaderboard, base_stats, uncursed_stats = pair
                    _write_ratings(base_fmt, filters, base_leaderboard, base_stats)
                    _write_ratings(uncursed_fmt, filters, uncursed_leaderboard, uncursed_stats)
                    processed.add(key)
                    processed.add(uncursed_key)
                    continue

        leaderboard, stats = ratings.compute_ratings(base_fmt, filters=filters)
        _write_ratings(base_fmt, filters, leaderboard, stats)
        processed.add(key)


def check_no_error_rows():
    """Hard-fail if any had_error:true row exists anywhere in results/current
    (see results_lib.find_had_error_rows) -- this script is normally run
    unattended, so a warning here would go unseen the same way the
    had_error rows themselves went unnoticed for an unknown length of time.
    Publishing must stop until strip_had_error.py + a rerun + splice clears
    them, not silently ship ratings fit around missing/erroring pairings."""
    error_rows = results_lib.find_had_error_rows()
    if not error_rows:
        return
    lines = "\n".join(
        f"  [{fmt}] {row.get('trainer1')} vs {row.get('trainer2')} "
        f"(seed {row.get('seed')}, result={row.get('result')})"
        for fmt, row in error_rows
    )
    raise RuntimeError(
        f"{len(error_rows)} had_error row(s) found in results/current -- "
        f"refusing to publish. Diagnose/fix and rerun those pairings (see "
        f"strip_had_error.py) before running export_web_data.py again:\n{lines}"
    )


def main():
    check_no_error_rows()
    card_data_by_label = results_lib.load_card_data()
    format_specs = build_format_specs(card_data_by_label)
    formats = [base + results_lib.filter_suffix(filters) for base, filters in format_specs]

    regenerate_analysis_outputs(format_specs)

    tribe_info = trainer_cards.load_tribe_info()
    max_native_dim = trainer_cards.max_native_sprite_dim(card_data_by_label)
    cell_sprite_budget = max_native_dim * trainer_cards.SPRITE_SCALE
    move_cols = trainer_cards.moveset_grid_columns(card_data_by_label, cell_sprite_budget)

    # Dataset-wide layout decisions (see trainer_cards.py's own docstrings)
    # apply to every format identically -- one shared file, not one per
    # format, since they don't actually vary by format.
    os.makedirs(WEB_DATA_DIR, exist_ok=True)
    with open(os.path.join(WEB_DATA_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({
            "moveGridColumns": move_cols,
            "maxNativeSpriteDim": max_native_dim,
            "spriteScale": trainer_cards.SPRITE_SCALE,
            # build_format_specs-derived list of format keys the site
            # actually has data for, so the frontend's format picker can
            # grey out combinations (e.g. uncursed + cursed_excluded, or an
            # uncursed variant of a filter whose whole cohort has no cursed
            # trainers) without hand-maintaining a second copy of this list
            # in TypeScript.
            "availableFormats": formats,
        }, f, indent=4)

    export_trainers(card_data_by_label, tribe_info, formats)
    export_team_levels(card_data_by_label)

    for fmt in formats:
        ratings_path = os.path.join(results_lib.RATINGS_DIR, f"ratings_{fmt}.json")
        if not os.path.exists(ratings_path):
            print(f"SKIPPED {fmt}: {ratings_path} not found")
            continue
        export_format(fmt, card_data_by_label)

    export_assets(card_data_by_label)


if __name__ == "__main__":
    main()
