r"""Render the DayOS sprout mark (assets/art/mark.svg) to the Windows icon assets/dayos.ico.

    .venv\Scripts\python.exe tools\make_icon.py

The mark sits on a warm cream rounded tile so it stays legible on both light
and dark taskbars.
"""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def main() -> None:
    app = QGuiApplication([])  # noqa: F841 - required for painting
    size = 256
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#F5F2E9"))
    painter.drawRoundedRect(QRectF(8, 8, size - 16, size - 16), 56, 56)
    QSvgRenderer(str(ASSETS / "art" / "mark.svg")).render(painter, QRectF(34, 30, size - 68, size - 68))
    painter.end()
    if not image.save(str(ASSETS / "dayos.ico")):
        raise SystemExit("Could not write dayos.ico")
    image.save(str(ASSETS / "dayos-256.png"))
    print(f"Wrote {ASSETS / 'dayos.ico'}")


if __name__ == "__main__":
    main()
