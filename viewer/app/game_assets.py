"""Lists selectable game assets (backdrops, BGM tracks) straight out of
vendor_dir, so dropdowns stay correct if the pinned engine build's asset
set ever changes, instead of hardcoding a name list here."""
import os


def list_backdrops(vendor_dir):
    """Battle backdrop names, e.g. "cave1" from Graphics/Battlebacks/cave1_bg.png.
    Only the *_bg.png files are selectable backdrops -- the same folder also
    holds non-selectable message-box/base variants."""
    backdrops_dir = os.path.join(vendor_dir, "Graphics", "Battlebacks")
    if not os.path.isdir(backdrops_dir):
        return []
    names = [
        f[: -len("_bg.png")]
        for f in os.listdir(backdrops_dir)
        if f.endswith("_bg.png")
    ]
    return sorted(names)


def list_bgm_tracks(vendor_dir):
    """BGM track names, e.g. "Battle wild" from Audio/BGM/Battle wild.ogg,
    for use with pbSetNextBattleBGM (which resolves a plain track name via
    pbResolveAudioFile)."""
    bgm_dir = os.path.join(vendor_dir, "Audio", "BGM")
    if not os.path.isdir(bgm_dir):
        return []
    names = [os.path.splitext(f)[0] for f in os.listdir(bgm_dir) if os.path.isfile(os.path.join(bgm_dir, f))]
    return sorted(names)
