"""Lists selectable game assets (backdrops, BGM tracks) straight out of
vendor_dir, so a raw name only ever comes from what's actually on disk (if
the pinned engine build's asset set changes, these lists follow it
automatically) -- but which of those raw names are actually selectable, and
what to call them, comes from asset_names.py's dicts: a raw name's presence
as a key there IS the whitelist, so trimming the dropdown down is just
deleting an entry, not touching this file.

Returns (raw_name, display_name) pairs, sorted by display_name -- raw_name
is what actually gets passed to the engine (ELO_REPLAY_BACKDROP / the BGM
track name), display_name is what the dropdown shows.
"""
import os

from app import asset_names

# Day is the bare environment name (no suffix, and always present); Evening/
# Night are only art for a handful of environments (city/field/forest/rocky/
# sand/snow/water as of this writing) -- resolve_backdrop falls back to Day
# for any environment that doesn't have a given time's art.
TIME_VARIANTS = [("day", "Day"), ("eve", "Evening"), ("night", "Night")]


def _backdrops_dir(vendor_dir):
    return os.path.join(vendor_dir, "Graphics", "Battlebacks")


def list_backdrop_environments(vendor_dir):
    """Base backdrop environments, e.g. ("cave1", "Cave (1)") from
    Graphics/Battlebacks/cave1_bg.png, filtered to asset_names.BACKDROP_NAMES.
    Time-of-day (_eve/_night) variants are a separate selector (see
    TIME_VARIANTS/resolve_backdrop below), not listed as their own entries
    here -- only the *_bg.png files are selectable backdrops at all, the
    same folder also holds non-selectable message-box/base variants."""
    backdrops_dir = _backdrops_dir(vendor_dir)
    if not os.path.isdir(backdrops_dir):
        return []
    available = {
        f[: -len("_bg.png")]
        for f in os.listdir(backdrops_dir)
        if f.endswith("_bg.png")
    }
    return _whitelisted_pairs(available, asset_names.BACKDROP_NAMES)


def resolve_backdrop(vendor_dir, environment, time_variant):
    """environment (e.g. "forest") + time_variant ("day"/"eve"/"night") ->
    actual raw backdrop name to pass as ELO_REPLAY_BACKDROP. Falls back to
    the bare (day) environment if e.g. "champion1_night" doesn't actually
    exist on disk -- most environments have no evening/night art at all."""
    if not environment or time_variant == "day":
        return environment
    candidate = f"{environment}_{time_variant}"
    if os.path.isfile(os.path.join(_backdrops_dir(vendor_dir), f"{candidate}_bg.png")):
        return candidate
    return environment


def list_bgm_tracks(vendor_dir):
    """BGM tracks, e.g. ("Battle wild", "Battle! Wild Pokemon") from
    Audio/BGM/Battle wild.ogg, filtered to asset_names.BGM_NAMES, for use
    with pbSetNextBattleBGM (which resolves a plain track name via
    pbResolveAudioFile)."""
    bgm_dir = os.path.join(vendor_dir, "Audio", "BGM")
    if not os.path.isdir(bgm_dir):
        return []
    available = {os.path.splitext(f)[0] for f in os.listdir(bgm_dir) if os.path.isfile(os.path.join(bgm_dir, f))}
    return _whitelisted_pairs(available, asset_names.BGM_NAMES)


def _whitelisted_pairs(available_raw_names, names_dict):
    """names_dict's own definition order, not alphabetical -- Luna curates
    that order deliberately (e.g. grouping gyms together), so re-sorting by
    display name here would silently discard it."""
    return [(raw, names_dict[raw]) for raw in names_dict if raw in available_raw_names]
