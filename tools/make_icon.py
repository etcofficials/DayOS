r"""Render assets/dayos.svg to a multi-size Windows icon (assets/dayos.ico).

    .venv\Scripts\python.exe tools\make_icon.py
"""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def main() -> None:
    app = QGuiApplication([])  # noqa: F841 - required for painting
    renderer = QSvgRenderer(str(ASSETS / "dayos.svg"))
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, 256, 256))
    painter.end()
    if not image.save(str(ASSETS / "dayos.ico")):
        raise SystemExit("Could not write dayos.ico")
    image.save(str(ASSETS / "dayos-256.png"))
    print(f"Wrote {ASSETS / 'dayos.ico'}")


if __name__ == "__main__":
    main()
