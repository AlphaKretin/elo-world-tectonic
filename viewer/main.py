import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from app.main_window import MainWindow

SPLASH_TEXT_COLOR = QColor("#f0f0f0")
SPLASH_MESSAGE_FLAGS = Qt.AlignBottom | Qt.AlignHCenter


def _build_splash_pixmap():
    # Painted in code rather than shipping an image asset -- this is a
    # boot-time-only placeholder shown for at most a few seconds, not worth
    # a packaged resource file.
    pixmap = QPixmap(420, 220)
    pixmap.fill(QColor("#20232a"))
    painter = QPainter(pixmap)
    painter.setPen(SPLASH_TEXT_COLOR)
    font = QFont()
    font.setPointSize(18)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect().adjusted(0, 0, 0, -40), Qt.AlignCenter, "Elo World Tectonic")
    font.setPointSize(11)
    font.setBold(False)
    painter.setFont(font)
    painter.drawText(pixmap.rect().adjusted(0, 40, 0, 0), Qt.AlignCenter, "Replay Viewer")
    painter.end()
    return pixmap


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("EloWorldTectonic")
    app.setApplicationName("Replay Viewer")

    splash = QSplashScreen(_build_splash_pixmap())
    splash.showMessage("Starting up...", SPLASH_MESSAGE_FLAGS, SPLASH_TEXT_COLOR)
    splash.show()
    app.processEvents()

    def report_progress(message):
        splash.showMessage(message, SPLASH_MESSAGE_FLAGS, SPLASH_TEXT_COLOR)
        # MainWindow's own construction below is what's actually slow (it's
        # all synchronous on this thread) -- processEvents() here is what
        # makes the message above actually repaint before that work starts,
        # rather than queuing behind it.
        app.processEvents()

    window = MainWindow(on_progress=report_progress)
    window.show()
    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
