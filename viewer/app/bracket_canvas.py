"""Custom-painted single-elimination bracket tree.

Converges from both edges toward a centered final, the way large brackets
are conventionally drawn (e.g. NCAA-style): round 0's 8 matches split into
a left half (indices 0-3) and a right half (indices 4-7), each stacked only
4 tall instead of all 16 entrants in one column, and each half's winners
progress inward round by round until they meet at the centered final. This
trades width (mirrored columns on both sides) for height (half as many
rows stacked per side) -- the previous single-direction layout stacked all
8 round-0 matches in one column, which read as cramped vertically.

Card x-position depends only on (round_idx, side) -- side being 'left',
'right', or 'center' for the lone final match -- while y-position still
follows the same bottom-up "midpoint of your two children" rule regardless
of side, since that's purely index-driven (match_idx // 2) and doesn't care
which direction the column grows. paintEvent mirrors the connector-drawing
logic per side: a left-side match connects rightward into its parent, a
right-side match connects leftward.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

DEFAULT_CARD_HEIGHT = 120  # fallback only; set_rounds is normally given the real content-driven height
DEFAULT_CARD_WIDTH = 210  # fallback only; set_rounds is normally given the real content-driven width
ROUND_GAP = 56
ROW_GAP = 14
TOP_MARGIN = 28
LEFT_MARGIN = 8


def _side_of(round_idx, match_idx, num_rounds, count):
    if round_idx == num_rounds - 1:
        return "center"
    return "left" if match_idx < count // 2 else "right"


class BracketCanvas(QWidget):
    """Owns one card widget per match, supplied externally via set_rounds
    (this widget only lays out and paints connectors, it doesn't know how
    a match card is built or what it means -- that's bracket_tab.py's job).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = []  # list of rounds, each a list of QWidget
        self._round_labels = []
        self._champion_label = None
        self._centers = []  # list of rounds, each a list of y-center ints
        self._total_width = 0
        self._card_height = DEFAULT_CARD_HEIGHT
        self._card_width = DEFAULT_CARD_WIDTH

    def set_rounds(self, round_names, card_rows, champion_text=None, card_height=None, card_width=None):
        """card_rows: list of rounds, each a list of card widgets already
        parented to this canvas; the last round must have exactly one
        match (the final). Replaces (and deletes) whatever this canvas
        was previously showing.

        card_height/card_width should be the tallest/widest card's actual
        sizeHint (the caller builds the cards, so it's in the best position
        to measure them) rather than a guessed constant -- a fixed guess
        either clips content or, if oversized, leaves a stretched gap
        around the footer buttons since the cards' QVBoxLayout has no
        stretch item to absorb the slack. This is one shared size for
        every card, not a per-card fit -- an unusually long name still
        clips instead of making its own card (and thus its own column)
        wider than the rest."""
        for old_round in self._cards:
            for card in old_round:
                if card is not None:
                    card.deleteLater()
        for label in self._round_labels:
            label.deleteLater()
        self._round_labels = []
        if self._champion_label is not None:
            self._champion_label.deleteLater()
            self._champion_label = None

        self._cards = card_rows
        self._card_height = card_height or DEFAULT_CARD_HEIGHT
        self._card_width = card_width or DEFAULT_CARD_WIDTH
        self._layout_cards()
        self._place_round_labels(round_names)
        if champion_text:
            self._place_champion_label(champion_text)
        self.update()

    def _x_of(self, round_idx, side):
        card_width = self._card_width
        if side == "center":
            return self._total_width // 2 - card_width // 2
        if side == "left":
            return LEFT_MARGIN + round_idx * (card_width + ROUND_GAP)
        return self._total_width - LEFT_MARGIN - card_width - round_idx * (card_width + ROUND_GAP)

    def _layout_cards(self):
        if not self._cards or not self._cards[0]:
            self._centers = []
            self._total_width = 0
            self.setMinimumSize(0, 0)
            return

        num_rounds = len(self._cards)
        round0_count = len(self._cards[0])
        half_count = round0_count // 2

        def local_row(match_idx):
            # Both halves stack over the *same* compact row range (not the
            # left half taking the top half of a double-height column and
            # the right half taking the bottom half) -- that's the whole
            # point of converging from both edges: half as many rows tall
            # as a single stacked column, not the same total height split
            # in two.
            return match_idx if match_idx < half_count else match_idx - half_count

        card_height = self._card_height
        centers = [
            [TOP_MARGIN + local_row(i) * (card_height + ROW_GAP) + card_height // 2 for i in range(round0_count)]
        ]
        for round_idx in range(1, num_rounds):
            prev = centers[round_idx - 1]
            count = len(self._cards[round_idx])
            centers.append([(prev[2 * i] + prev[2 * i + 1]) // 2 for i in range(count)])
        self._centers = centers

        # Outer columns run from round 0 (edge) inward to the second-to-last
        # round (just before the centered final); the final itself doesn't
        # get its own left/right slot, it sits in the middle at half the
        # total canvas width.
        card_width = self._card_width
        inner_r = max(num_rounds - 2, 0)
        x_center = LEFT_MARGIN + inner_r * (card_width + ROUND_GAP) + card_width + ROUND_GAP
        self._total_width = 2 * x_center + card_width if num_rounds > 1 else card_width + 2 * LEFT_MARGIN

        for round_idx, cards in enumerate(self._cards):
            count = len(cards)
            for match_idx, card in enumerate(cards):
                if card is None:
                    continue
                side = _side_of(round_idx, match_idx, num_rounds, count)
                x = self._x_of(round_idx, side)
                y_center = centers[round_idx][match_idx]
                card.setParent(self)
                card.setGeometry(x, y_center - card_height // 2, card_width, card_height)
                card.show()

        # Bottom edge of the last row, not half_count full row-heights --
        # the previous formula counted one extra (card_height + ROW_GAP)
        # past the actual last card, which left enough slack below the
        # content to trigger an unnecessary vertical scrollbar. No bottom
        # padding added on top of that either, by request -- the last card
        # abutting the viewport's bottom edge reads better than a gap.
        total_height = TOP_MARGIN + (half_count - 1) * (card_height + ROW_GAP) + card_height
        self.setMinimumSize(self._total_width, total_height)

    def _place_round_labels(self, round_names):
        num_rounds = len(self._cards)
        for round_idx, name in enumerate(round_names):
            if round_idx >= num_rounds:
                break
            if round_idx == num_rounds - 1:
                sides = ["center"]
            else:
                sides = ["left", "right"]
            for side in sides:
                label = QLabel(name, self)
                label.setAlignment(Qt.AlignCenter)
                x = self._x_of(round_idx, side)
                label.setGeometry(x, 0, self._card_width, TOP_MARGIN - 4)
                label.show()
                self._round_labels.append(label)

    def _place_champion_label(self, text):
        num_rounds = len(self._cards)
        final_y = self._centers[-1][0] if self._centers else TOP_MARGIN
        x = self._x_of(num_rounds - 1, "center")
        label = QLabel(text, self)
        label.setAlignment(Qt.AlignCenter)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setGeometry(x, final_y + self._card_height // 2 + 4, self._card_width, 20)
        label.show()
        self._champion_label = label

    def paintEvent(self, event):
        super().paintEvent(event)
        if len(self._centers) < 2:
            return
        painter = QPainter(self)
        pen = QPen(self.palette().color(self.foregroundRole()))
        pen.setWidth(2)
        painter.setPen(pen)

        num_rounds = len(self._cards)
        for round_idx in range(num_rounds - 1):
            count = len(self._cards[round_idx])
            parent_count = len(self._cards[round_idx + 1])
            for match_idx, y_center in enumerate(self._centers[round_idx]):
                side = _side_of(round_idx, match_idx, num_rounds, count)
                parent_side = _side_of(round_idx + 1, match_idx // 2, num_rounds, parent_count)
                parent_y = self._centers[round_idx + 1][match_idx // 2]

                if side == "left":
                    x_edge = self._x_of(round_idx, side) + self._card_width
                    x_mid = x_edge + ROUND_GAP // 2
                    parent_edge = self._x_of(round_idx + 1, parent_side)
                else:  # "right" (a child is never "center")
                    x_edge = self._x_of(round_idx, side)
                    x_mid = x_edge - ROUND_GAP // 2
                    parent_edge = self._x_of(round_idx + 1, parent_side) + self._card_width

                painter.drawLine(x_edge, y_center, x_mid, y_center)
                painter.drawLine(x_mid, y_center, x_mid, parent_y)
                # Drawn per-child rather than once per sibling pair: for
                # every transition except the one feeding the centered
                # final, both siblings share the same side and so the same
                # x_mid -> parent_edge segment (redundant but harmless to
                # draw twice). At the final transition specifically, the
                # left and right semifinalists approach from opposite
                # sides with different x_mid values, so each needs its own
                # stub drawn -- a "just the second sibling" condition here
                # would silently drop the left semifinal's line.
                painter.drawLine(x_mid, parent_y, parent_edge, parent_y)
