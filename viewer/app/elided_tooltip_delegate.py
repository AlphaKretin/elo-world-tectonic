"""Shows a cell's full text as a tooltip only when the cell is actually too
narrow to show it and Qt has visually elided it -- an always-on tooltip for
every cell (e.g. every trainer name) was rejected as too distracting;
this only kicks in exactly where truncation is actually hiding something.

Shared across Battles' trainer-name columns and the Trainers tab's own
Name/Opponent columns, which had independently grown inconsistent (one had
a raw-label tooltip always on, the others had none at all) before
converging on this."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QStyledItemDelegate, QToolTip

# Rough compensation for the small internal margin QStyledItemDelegate's own
# paint() insets text by (style-dependent, roughly PM_FocusFrameHMargin on
# each side) that option.rect doesn't already account for -- without this,
# text just barely fitting on screen can wrongly report as elided.
_TEXT_MARGIN_FUDGE = 8


class ElidedTooltipDelegate(QStyledItemDelegate):
    def helpEvent(self, event, view, option, index):
        if event is None or event.type() != QEvent.ToolTip:
            return super().helpEvent(event, view, option, index)

        self.initStyleOption(option, index)
        text = option.text
        available_width = option.rect.width() - _TEXT_MARGIN_FUDGE
        elided = option.fontMetrics.elidedText(text, option.textElideMode, available_width)
        if text and elided != text:
            QToolTip.showText(event.globalPos(), text, view)
        else:
            QToolTip.hideText()
        return True
