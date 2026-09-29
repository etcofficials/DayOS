"""Botanical artwork: bundled SVGs painted crisply at any size, recoloured per theme."""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from src.config import resource_root
from src.ui.theme import theme

log = logging.getLogger(__name__)

# Light artwork colour -> dark theme colour (see tools/make_art.py).
ART_DARK = {
    "#71896C": "#7E9775", "#8FA77F": "#6A8262", "#AFC2A2": "#586C53", "#5E7458": "#8CA383",
    "#C77D59": "#A86C4E", "#B06C4B": "#8C5A41", "#E3A47E": "#CC8F6B", "#E8E2D3": "#343D35",
    "#DCD3C1": "#3F4A40", "#EFF1E7": "#2A322B", "#E1E7DA": "#2C352D", "#CFDAC9": "#334034",
    "#B9C8B2": "#3C4B3D", "#F3F4EC": "#242B25",
}

_svg_text: dict[str, str] = {}
_renderers: dict[tuple[str, str], QSvgRenderer] = {}
_pixmaps: dict[tuple, QPixmap] = {}


def _load(name: str) -> str:
    if name not in _svg_text:
        path = resource_root() / "assets" / "art" / f"{name}.svg"
        try:
            _svg_text[name] = path.read_text(encoding="utf-8")
        except OSError:
            log.warning("Missing artwork %s", path)
            _svg_text[name] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
    return _svg_text[name]


def renderer(name: str) -> QSvgRenderer:
    key = (name, theme.mode)
    if key not in _renderers:
        text = _load(name)
        if theme.mode == "dark":
            for light, dark in ART_DARK.items():
                text = text.replace(light, dark)
        _renderers[key] = QSvgRenderer(QByteArray(text.encode("utf-8")))
    return _renderers[key]


def art_pixmap(name: str, width: int, height: int) -> QPixmap:
    """Render artwork to a device-pixel-ratio aware pixmap (cached)."""
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0  # type: ignore[union-attr]
    key = (name, theme.mode, width, height, dpr)
    if key not in _pixmaps:
        pm = QPixmap(QSize(max(1, int(width * dpr)), max(1, int(height * dpr))))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer(name).render(p, QRectF(0, 0, width * dpr, height * dpr))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _pixmaps[key] = pm
    return _pixmaps[key]


def _clear_cache() -> None:
    _pixmaps.clear()


theme.changed.connect(_clear_cache)


class Art(QWidget):
    """Decorative, mouse-transparent artwork that keeps its aspect ratio.

    ``align`` positions the drawing inside the widget (e.g. bottom-right) and
    ``opacity`` keeps decoration quiet behind content.
    """

    def __init__(self, name: str, width: int, height: int,
                 align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
                 opacity: float = 1.0, parent: QWidget | None = None, fill_width: bool = False,
                 clip_radius: float = 0.0) -> None:
        super().__init__(parent)
        self.name = name
        self._fill_width = fill_width
        self._clip_radius = clip_radius
        self._base = QSize(width, height)
        self._align = align
        self._opacity = opacity
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumSize(1, 1)
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._base

    def paintEvent(self, _event) -> None:  # noqa: N802
        vb = renderer(self.name).viewBoxF()
        if vb.width() <= 0 or vb.height() <= 0:
            return
        if self._fill_width:
            scale = self.width() / vb.width()
        else:
            scale = min(self.width() / vb.width(), self.height() / vb.height())
        w, h = int(vb.width() * scale), int(vb.height() * scale)
        if w < 2 or h < 2:
            return
        x = 0 if self._align & Qt.AlignmentFlag.AlignLeft else (
            self.width() - w if self._align & Qt.AlignmentFlag.AlignRight else (self.width() - w) // 2)
        y = 0 if self._align & Qt.AlignmentFlag.AlignTop else (
            self.height() - h if self._align & Qt.AlignmentFlag.AlignBottom else (self.height() - h) // 2)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)
        if self._clip_radius:
            path = QPainterPath()
            r = self._clip_radius
            path.addRoundedRect(QRectF(self.rect()).adjusted(0, -r, 0, 0), r, r)
            p.setClipPath(path)
        p.drawPixmap(x, y, art_pixmap(self.name, w, h))
        p.end()
