"""DayOS line icons: small, original 24×24 stroke drawings rendered with QtSvg.

Icons are recolored from theme tokens and re-rendered automatically when the
theme changes (see :func:`bind_icon`).
"""

from __future__ import annotations

import weakref
from typing import Any

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from src.ui.theme import theme

_P = {
    "today": '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/>',
    "tasks": '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8.5 12.2l2.4 2.4 4.6-5"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "study": '<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 2M10 3h4"/>',
    "exams": '<path d="M4 6.5C6.5 5 9.5 5 12 6.5 14.5 5 17.5 5 20 6.5V19c-2.5-1.5-5.5-1.5-8 0-2.5-1.5-5.5-1.5-8 0z"/><path d="M12 6.5V19"/>',
    "notes": '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5M9 12.5h7M9 16h5"/>',
    "habits": '<path d="M5 12a7 7 0 0 1 12-4.9M19 12a7 7 0 0 1-12 4.9"/><path d="M17.5 3.5v4h-4M6.5 20.5v-4h4"/>',
    "goals": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8"/>',
    "insights": '<path d="M4 20h16"/><path d="M7 16v-4M12 16V7M17 16v-6"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    "trash": '<path d="M5 7h14M10 4h4M7 7l1 13h8l1-13"/><path d="M10.5 11v5.5M13.5 11v5.5"/>',
    "edit": '<path d="M5 19l1-4L15.5 5.5a2.1 2.1 0 0 1 3 3L9 18z"/><path d="M13.5 7.5l3 3"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "chev-left": '<path d="M14.5 6l-6 6 6 6"/>',
    "chev-right": '<path d="M9.5 6l6 6-6 6"/>',
    "chev-down": '<path d="M6 9.5l6 6 6-6"/>',
    "chev-up": '<path d="M6 14.5l6-6 6 6"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "sidebar": '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M9 4.5v15"/>',
    "pin": '<path d="M9 4h6l-1 5 3 3v1.5H7V12l3-3z"/><path d="M12 13.5V20"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z"/>',
    "pause": '<path d="M8.5 5.5v13M15.5 5.5v13"/>',
    "reset": '<path d="M5 12a7 7 0 1 0 2.1-5"/><path d="M5 4v4h4"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
    "flame": '<path d="M12 20.5c3.6 0 6-2.4 6-5.8 0-3.7-3.2-5.7-4.2-9.7-2.3 1.4-3.3 3.7-3.1 6-1.2-.6-1.9-1.8-2-2.9C7 9.8 6 11.9 6 14.7c0 3.4 2.4 5.8 6 5.8z"/>',
    "more": '<circle cx="6" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="18" cy="12" r="1"/>',
    "archive": '<rect x="3.5" y="4.5" width="17" height="4" rx="1.5"/><path d="M5 8.5V19h14V8.5M10 12.5h4"/>',
    "undo": '<path d="M9 14L4.5 9.5 9 5"/><path d="M4.5 9.5H14a5.5 5.5 0 0 1 0 11h-3"/>',
    "download": '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
    "upload": '<path d="M12 15V4M7.5 8.5L12 4l4.5 4.5M5 19.5h14"/>',
    "flag": '<path d="M6 21V4M6 4.5h11l-2 4 2 4H6"/>',
    "book": '<path d="M5 4.5h11a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
    "coffee": '<path d="M5 9h11v5a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5z"/><path d="M16 10.5h1.5a2.5 2.5 0 0 1 0 5H16M8.5 3.5v2.5M12 3.5v2.5"/>',
    "moon": '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2"/>',
    "list": '<path d="M9 7h11M9 12h11M9 17h11"/><circle cx="4.8" cy="7" r=".8"/><circle cx="4.8" cy="12" r=".8"/><circle cx="4.8" cy="17" r=".8"/>',
    "grid": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M4 10h16M4 15h16M9.5 10v10M14.5 10v10"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4.5M12 17.2v.3"/>',
    "info": '<circle cx="12" cy="12" r="8"/><path d="M12 11v5.5M12 7.8v.4"/>',
    "leaf": '<path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14z"/><path d="M5 19l7-7"/>',
    "keyboard": '<rect x="3" y="6" width="18" height="12" rx="3"/><path d="M7 10h.5M11 10h.5M15 10h.5M8 14.5h8"/>',
    "database": '<ellipse cx="12" cy="6.5" rx="7" ry="2.5"/><path d="M5 6.5v11c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-11M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
    "folder": '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "sparkle": '<path d="M12 4c.6 3.8 2.2 5.4 6 6-3.8.6-5.4 2.2-6 6-.6-3.8-2.2-5.4-6-6 3.8-.6 5.4-2.2 6-6z"/>',
    "subject": '<path d="M4 7.5L12 4l8 3.5-8 3.5z"/><path d="M7 9v5c1.5 1.5 3 2 5 2s3.5-.5 5-2V9"/>',
    "mistake": '<circle cx="12" cy="12" r="8"/><path d="M9.5 9.5l5 5M14.5 9.5l-5 5"/>',
    "chart": '<path d="M4 18l5-6 4 3 7-8"/><path d="M15.5 7H20v4.5"/>',
    "moon-star": '<path d="M18.5 14.5A7 7 0 0 1 9.5 5.5a7 7 0 1 0 9 9z"/>',
    "inbox": '<path d="M4 13.5l2.2-7.2A2 2 0 0 1 8.1 5h7.8a2 2 0 0 1 1.9 1.3L20 13.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M4 13.5h4.5l1.5 2.5h4l1.5-2.5H20"/>',
    "bell": '<path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.5H5z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
    "command": '<path d="M9 9V6.5A2.5 2.5 0 1 0 6.5 9H9zm0 0h6m-6 0v6m6-6V6.5A2.5 2.5 0 1 1 17.5 9H15zm0 0v6m0 0h-6m6 0v2.5a2.5 2.5 0 1 0 2.5-2.5H15zm-6 0v2.5A2.5 2.5 0 1 1 6.5 15H9z"/>',
    "clipboard": '<rect x="5.5" y="5" width="13" height="16" rx="2.5"/><path d="M9 5a3 3 0 0 1 6 0v1H9z"/><path d="M9 11h6M9 15h4"/>',
    "money": '<rect x="3.5" y="6.5" width="17" height="11" rx="2.5"/><circle cx="12" cy="12" r="2.6"/><path d="M6.5 9.5v5M17.5 9.5v5"/>',
    "project": '<path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h3l2 2h6A2.5 2.5 0 0 1 20 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5z"/><path d="M9 13.5h6"/>',
    "skill": '<path d="M4 19h4v-5H4zM10 19h4V9h-4zM16 19h4V5h-4z"/>',
    "audio": '<path d="M5 9.5h3.5L13 5.5v13l-4.5-4H5z"/><path d="M16.5 9a4.5 4.5 0 0 1 0 6M18.8 6.5a8 8 0 0 1 0 11"/>',
    "mic": '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/>',
    "headphones": '<path d="M4.5 15v-3a7.5 7.5 0 0 1 15 0v3"/><rect x="3.5" y="14" width="4" height="6" rx="1.6"/><rect x="16.5" y="14" width="4" height="6" rx="1.6"/>',
    "cloud": '<path d="M7.5 18.5a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17.6 9.6 4.5 4.5 0 0 1 17 18.5z"/>',
    "rain": '<path d="M7.5 15a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17.6 6.1 4.5 4.5 0 0 1 17 15z"/><path d="M9 18l-1 2.5M13 18l-1 2.5M17 18l-1 2.5"/>',
    "news": '<path d="M5 5.5h11v13a1.5 1.5 0 0 1-1.5 1.5H6.5A1.5 1.5 0 0 1 5 18.5z"/><path d="M16 9h3v9.5a1.5 1.5 0 0 1-3 0M8 9h5M8 12.5h5M8 16h3"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "brain": '<path d="M9.5 4.5a3 3 0 0 0-3 3 3 3 0 0 0-1.5 5.3A3 3 0 0 0 8 18a2.5 2.5 0 0 0 4 1.5V6a2 2 0 0 0-2.5-1.5zM14.5 4.5a3 3 0 0 1 3 3 3 3 0 0 1 1.5 5.3A3 3 0 0 1 16 18a2.5 2.5 0 0 1-4 1.5"/>',
    "file-search": '<path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h4"/><path d="M13.5 3.5L18 8v3M13.5 3.5V8H18"/><circle cx="16" cy="16" r="3"/><path d="M18.2 18.2l2.3 2.3"/>',
    "repeat": '<path d="M5 10V9a3 3 0 0 1 3-3h10l-3-3M19 14v1a3 3 0 0 1-3 3H6l3 3"/>',
    "tag": '<path d="M4 4.5h7l8.5 8.5-7 7L4 11.5z"/><circle cx="8" cy="8.5" r="1.2"/>',
    "code": '<path d="M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5M13.5 5l-3 14"/>',
    "terminal": '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M7 10l3 2-3 2M12.5 14.5H17"/>',
    "lightbulb": '<path d="M9 17.5h6M10 20.5h4M12 3.5a6 6 0 0 0-3.5 10.9V16h7v-1.6A6 6 0 0 0 12 3.5z"/>',
    "routine": '<path d="M12 4.5v3M12 16.5v3M4.5 12h3M16.5 12h3"/><circle cx="12" cy="12" r="3.5"/>',
    "drive": '<rect x="3.5" y="7" width="17" height="10" rx="2.5"/><path d="M7 13.5h.5M10 13.5h.5"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="2.2"/><path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
    "star": '<path d="M12 4l2.4 5 5.4.6-4 3.7 1.1 5.3L12 16l-4.9 2.6 1.1-5.3-4-3.7 5.4-.6z"/>',
    "external": '<path d="M13 5h6v6M19 5l-8 8"/><path d="M17 13.5V18a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 5 18V8.5A1.5 1.5 0 0 1 6.5 7H11"/>',
    "refresh": '<path d="M19 7.5A8 8 0 1 0 20 12"/><path d="M19.5 3.5v4h-4"/>',
    "shield": '<path d="M12 3.5l7 2.5v5.5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
    "filter": '<path d="M4.5 5.5h15l-6 7v5.5l-3 1.5v-7z"/>',
    "wand": '<path d="M5 19L15.5 8.5M14 5v2M19 10h-2M17.5 6.5l-1.4 1.4"/><path d="M13.5 9.5l1 1"/>',
    "pin-off": '<path d="M9 4h6l-1 5 3 3v1.5H7V12l3-3z"/><path d="M12 13.5V20M4 4l16 16"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "pause-circle": '<circle cx="12" cy="12" r="8"/><path d="M10 9v6M14 9v6"/>',
    "list-check": '<path d="M10 7h10M10 12h10M10 17h10"/><path d="M3.5 7l1.5 1.5L7.5 6M3.5 12l1.5 1.5 2.5-2.5M3.5 17l1.5 1.5 2.5-2.5"/>',
}

_cache: dict[tuple[str, str, int, float], QPixmap] = {}


def svg_markup(name: str, color: str, stroke: float = 1.7) -> str:
    body = _P.get(name, _P["info"])
    fill = color if name in ("play",) else "none"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0  # type: ignore[union-attr]
    key = (name, color, size, dpr)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color).encode("utf-8")))
    pm = QPixmap(QSize(int(size * dpr), int(size * dpr)))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm
    return pm


def icon(name: str, color_key: str = "text2", size: int = 18, active_key: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, theme.tokens.get(color_key, color_key), size), QIcon.Mode.Normal, QIcon.State.Off)
    if active_key:
        ic.addPixmap(pixmap(name, theme.tokens.get(active_key, active_key), size), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, theme.tokens["text3"], size), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


_bound: list[tuple[Any, str, str, int, str | None]] = []


def bind_icon(widget: Any, name: str, color_key: str = "text2", size: int = 18, active_key: str | None = None) -> None:
    """Set an icon on a button/action and keep it in sync with the theme."""
    widget.setIcon(icon(name, color_key, size, active_key))
    if hasattr(widget, "setIconSize"):
        widget.setIconSize(QSize(size, size))
    for i, (ref, *_rest) in enumerate(_bound):
        if ref() is widget:
            _bound[i] = (ref, name, color_key, size, active_key)
            return
    _bound.append((weakref.ref(widget), name, color_key, size, active_key))


def _refresh_bound() -> None:
    _cache.clear()
    alive = []
    for ref, name, color_key, size, active_key in _bound:
        widget = ref()
        if widget is None or not isValid(widget):
            continue
        widget.setIcon(icon(name, color_key, size, active_key))
        alive.append((ref, name, color_key, size, active_key))
    _bound[:] = alive


theme.changed.connect(_refresh_bound)
