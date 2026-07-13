import os
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from app.main_window import MainWindow

APP_TITLE = "Battle Station"
SPLASH_TEXT_COLOR = QColor("#f0f0f0")
SPLASH_MESSAGE_FLAGS = Qt.AlignBottom | Qt.AlignHCenter

# Mirrors app/config.py's frozen-vs-dev split: in a PyInstaller onedir build
# assets/ is collected as a sibling of viewer.exe (see viewer.spec's datas=);
# in a dev checkout it's a sibling of this file.
if getattr(sys, "frozen", False):
    ASSETS_DIR = os.path.join(os.path.dirname(sys.executable), "assets")
else:
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _build_splash_pixmap():
    # Painted in code rather than shipping a full image asset -- this is a
    # boot-time-only screen shown for at most a few seconds, not worth a
    # fully composed resource file. The trainer sprite is the one exception:
    # it's cheap to load and gives the splash a face. Everything here is
    # centered in a vertical stack (titles, then sprite) -- the bottom strip
    # is left clear for QSplashScreen's own showMessage() progress text.
    pixmap = QPixmap(420, 220)
    pixmap.fill(QColor("#20232a"))
    painter = QPainter(pixmap)

    painter.setPen(SPLASH_TEXT_COLOR)
    font = QFont()
    font.setPointSize(10)
    font.setBold(False)
    painter.setFont(font)
    painter.drawText(QRect(0, 14, pixmap.width(), 20), Qt.AlignHCenter, "Pokémon Tectonic Elo World")
    font.setPointSize(20)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(0, 34, pixmap.width(), 32), Qt.AlignHCenter, APP_TITLE)

    sprite = QPixmap(os.path.join(ASSETS_DIR, "scientist_f.png"))
    if not sprite.isNull():
        sprite = sprite.scaled(96, 96, Qt.KeepAspectRatio, Qt.FastTransformation)
        painter.drawPixmap((pixmap.width() - sprite.width()) // 2, 84, sprite)

    painter.end()
    return pixmap


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("EloWorldTectonic")
    app.setApplicationName(APP_TITLE)
    app.setWindowIcon(QIcon(os.path.join(ASSETS_DIR, "app_icon.png")))

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
