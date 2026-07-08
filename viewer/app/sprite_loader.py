"""Trainer portrait sprites (Graphics/Trainers/<trainer_type>.png) with an
optional composited curse-badge corner (Graphics/Items/TAROTAMULET_ACTIVE.png),
nearest-neighbor-scaled and HiDPI-correct. Extracted out of BracketTab (its
original, single consumer) so any tab wanting trainer art -- the bracket's
small match-card sprites, the Trainers tab's much larger profile sprite --
can share it without depending on bracket-specific state; every method here
only ever touched self.config and two caller-supplied resolvers.

Different callers want different display sizes (a bracket has ~16 cards on
screen at once; a trainer profile page is dedicated to just one), so size is
a per-call argument rather than fixed at construction. Source art is native
160x160 (trainer) / 48x48 (curse badge) pixel art; scaling snaps the
requested size to the nearest clean integer multiple/divisor of that native
size rather than an arbitrary float resize, so nearest-neighbor scaling
stays crisp instead of blurring at an off-ratio size."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap

NATIVE_SPRITE_SIZE = 160
NATIVE_CURSE_BADGE_SIZE = 48


def snap_to_clean_scale(native_size, requested_size):
    """Nearest clean integer multiple/divisor of native_size to
    requested_size -- e.g. 160 native, 40 requested -> 40 (exact 4x
    downscale); 160 native, 150 requested -> 160 (1x, since no other
    integer scale lands closer to 150 than the source resolution itself)."""
    if requested_size >= native_size:
        factor = max(1, round(requested_size / native_size))
        return native_size * factor
    factor = max(1, round(native_size / requested_size))
    return max(1, native_size // factor)


class SpriteLoader:
    def __init__(self, config, trainer_data_provider, is_cursed_fn):
        """trainer_data_provider: zero-arg callable -> {label: row}.
        is_cursed_fn: (label) -> bool."""
        self.config = config
        self._trainer_data = trainer_data_provider
        self._is_cursed = is_cursed_fn
        self._sprite_cache = {}  # (label, size, badge_size) -> QPixmap|None
        self._curse_badge_cache = {}  # size -> QPixmap|None

    def _device_pixel_ratio(self):
        screen = QGuiApplication.primaryScreen()
        return screen.devicePixelRatio() if screen else 1.0

    def _scaled_pixel_art(self, raw, native_size, requested_size):
        """Nearest-neighbor scale to the requested_size snapped against
        native_size, rendered at the screen's actual device pixel ratio and
        tagged with that ratio via setDevicePixelRatio -- without this, a
        pixmap with no DPR set gets silently re-stretched a *second* time by
        Qt when painted on a HiDPI screen (to match the screen's real
        physical pixel density), and that implicit second pass isn't
        nearest-neighbor. Returns (pixmap, logical_size) -- logical_size is
        the actual snapped size used, which callers compositing on top
        (e.g. badge placement) need instead of the originally requested size."""
        logical_size = snap_to_clean_scale(native_size, requested_size)
        dpr = self._device_pixel_ratio()
        physical = max(1, round(logical_size * dpr))
        scaled = raw.scaled(physical, physical, Qt.KeepAspectRatio, Qt.FastTransformation)
        scaled.setDevicePixelRatio(dpr)
        return scaled, logical_size

    def curse_badge(self, size):
        """Tarot Amulet badge (Graphics/Items/TAROTAMULET_ACTIVE.png), the
        same icon trainer_cards.py/the website use to mark a curse-rolled
        trainer -- loaded once per requested size and composited onto a
        cursed trainer's sprite corner (see sprite_pixmap)."""
        if size not in self._curse_badge_cache:
            pixmap = None
            path = os.path.join(self.config.vendor_dir, "Graphics", "Items", "TAROTAMULET_ACTIVE.png")
            if os.path.isfile(path):
                raw = QPixmap(path)
                if not raw.isNull():
                    pixmap, _ = self._scaled_pixel_art(raw, NATIVE_CURSE_BADGE_SIZE, size)
            self._curse_badge_cache[size] = pixmap
        return self._curse_badge_cache[size]

    def sprite_pixmap(self, label, size, badge_size=None):
        """Trainer portrait sprite (Graphics/Trainers/{trainer_type}.png,
        the same one trainer_cards.py uses) scaled to size, with the curse
        badge composited onto its bottom-right corner for a curse-rolled
        trainer -- only if badge_size is given; pass None to skip badge
        compositing entirely regardless of curse status. Cached per
        (label, size, badge_size) since the same trainer recurs across many
        matches/rounds or repeated lookups. None if the label has no
        card-data row yet or the sprite file is missing (e.g. a hand-typed
        label)."""
        if not label:
            return None
        cache_key = (label, size, badge_size)
        if cache_key not in self._sprite_cache:
            pixmap = None
            logical_size = None
            row = self._trainer_data().get(label)
            trainer_type = row.get("trainer_type") if row else None
            if trainer_type:
                path = os.path.join(self.config.vendor_dir, "Graphics", "Trainers", f"{trainer_type}.png")
                if os.path.isfile(path):
                    raw = QPixmap(path)
                    if not raw.isNull():
                        pixmap, logical_size = self._scaled_pixel_art(raw, NATIVE_SPRITE_SIZE, size)
            if pixmap is not None and badge_size is not None and self._is_cursed(label):
                badge = self.curse_badge(badge_size)
                if badge is not None:
                    dpr = pixmap.devicePixelRatio()
                    composed = QPixmap(pixmap.size())
                    composed.setDevicePixelRatio(dpr)
                    composed.fill(Qt.transparent)
                    painter = QPainter(composed)
                    painter.drawPixmap(0, 0, pixmap)
                    # Positions are in the painter's logical coordinate
                    # space (the composed pixmap's tagged DPR), so the
                    # actual snapped logical_size (not pixmap.width()/
                    # height(), which are physical pixel counts, and not
                    # the originally requested size, which may have been
                    # snapped to something else) is what to subtract.
                    painter.drawPixmap(logical_size - badge_size, logical_size - badge_size, badge)
                    painter.end()
                    pixmap = composed
            self._sprite_cache[cache_key] = pixmap
        return self._sprite_cache[cache_key]
