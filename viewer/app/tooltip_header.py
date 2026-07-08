"""QHeaderView never shows a tooltip for a section's Qt.ToolTipRole header
data on its own -- a longstanding Qt limitation (QHeaderView doesn't route
QEvent.ToolTip through the model the way QAbstractItemView's body cells do).
install_header_tooltips adds that behavior via an event filter on the
header Qt already created for the table, rather than replacing the header
widget outright.

Replacing it (QTableView.setHorizontalHeader(CustomHeaderView(...))) was
tried first and turned out to silently drop the header's own click-to-sort
wiring -- sectionsClickable() came back False on the replacement instead of
True, breaking header-click sorting on every table it touched. An event
filter on the header Qt already built leaves all of that alone."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QToolTip


class _HeaderTooltipFilter(QObject):
    def eventFilter(self, header, event):
        if event.type() == QEvent.ToolTip:
            index = header.logicalIndexAt(event.pos())
            text = header.model().headerData(index, header.orientation(), Qt.ToolTipRole) if index >= 0 else None
            if text:
                QToolTip.showText(event.globalPos(), str(text), header)
            else:
                QToolTip.hideText()
            return True
        return False


def install_header_tooltips(table):
    """table: any QTableView/QTableWidget whose horizontal header carries
    Qt.ToolTipRole data (a QTableWidgetItem's setToolTip, or a custom
    model's headerData override) that should actually show on hover."""
    header = table.horizontalHeader()
    header.installEventFilter(_HeaderTooltipFilter(header))
