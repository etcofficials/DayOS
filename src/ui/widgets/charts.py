"""Small QPainter charts. No chart library; values come straight from the database."""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from src.ui.theme import theme


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(value))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= m * exp:
            return m * exp
    return 10 * exp


def _small_font(pt: float = 8.5) -> QFont:
    f = QFont("Segoe UI")
    f.setPointSizeF(pt)
    return f


class BarChart(QWidget):
    """Vertical bars with a light grid, hover values and adaptive labels."""

    def __init__(self, color_key: str = "accent", formatter: Callable[[float], str] | None = None,
                 parent: QWidget | None = None, integer: bool = False) -> None:
        super().__init__(parent)
        self._integer = integer
        self._data: list[tuple[str, float]] = []
        self._color_key = color_key
        self._fmt = formatter or (lambda v: f"{v:g}")
        self._highlight_last = False
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hover = -1
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 200)

    def set_data(self, data: list[tuple[str, float]], highlight_last: bool = False) -> None:
        self._data = data
        self._highlight_last = highlight_last
        summary = ", ".join(f"{label}: {self._fmt(v)}" for label, v in data[-14:])
        self.setAccessibleDescription(summary)
        self.update()

    def _geometry(self) -> tuple[QRectF, float]:
        fm = QFontMetrics(_small_font())
        top_value = _nice_max(max((v for _, v in self._data), default=0))
        if self._integer:
            top_value = max(3, math.ceil(top_value / 3) * 3)
        left = fm.horizontalAdvance(self._fmt(top_value)) + 10
        plot = QRectF(left, 10, self.width() - left - 6, self.height() - 10 - fm.height() - 10)
        return plot, top_value

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._data:
            return
        plot, _ = self._geometry()
        slot = plot.width() / len(self._data)
        idx = int((event.position().x() - plot.left()) // slot) if slot > 0 else -1
        if 0 <= idx < len(self._data) and plot.left() <= event.position().x() <= plot.right():
            if idx != self._hover:
                self._hover = idx
                label, value = self._data[idx]
                QToolTip.showText(event.globalPosition().toPoint(), f"{label}: {self._fmt(value)}", self)
                self.update()
        elif self._hover != -1:
            self._hover = -1
            QToolTip.hideText()
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(_small_font())
        fm = p.fontMetrics()
        plot, top_value = self._geometry()
        grid = theme.color("chart_grid")
        text3 = theme.color("text3")
        # grid lines + y labels
        for i in range(4):
            y = plot.bottom() - plot.height() * i / 3
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(text3)
            p.drawText(QRectF(0, y - fm.height() / 2, plot.left() - 6, fm.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._fmt(top_value * i / 3))
        if not self._data:
            p.end()
            return
        n = len(self._data)
        slot = plot.width() / n
        bar_w = max(3.0, min(34.0, slot * 0.62))
        max_labels = max(1, int(plot.width() // (fm.horizontalAdvance("00/00") + 8)))
        step = max(1, math.ceil(n / max_labels))
        color = theme.color(self._color_key)
        soft = QColor(color)
        soft.setAlphaF(0.55)
        for i, (lbl, value) in enumerate(self._data):
            cx = plot.left() + slot * (i + 0.5)
            h = 0 if top_value == 0 else plot.height() * value / top_value
            if value > 0:
                h = max(h, 2.0)
                rect = QRectF(cx - bar_w / 2, plot.bottom() - h, bar_w, h)
                path = QPainterPath()
                r = min(4.0, bar_w / 2, h)
                path.addRoundedRect(rect.adjusted(0, 0, 0, r), r, r)
                p.save()
                p.setClipRect(QRectF(rect.left() - 1, rect.top() - 1, rect.width() + 2, rect.height() + 1))
                p.setPen(Qt.PenStyle.NoPen)
                emphasized = i == self._hover or (self._highlight_last and i == n - 1)
                p.setBrush(color if emphasized or self._hover == -1 and not self._highlight_last else soft)
                p.drawPath(path)
                p.restore()
            if i % step == 0 or i == n - 1 and n <= max_labels:
                p.setPen(text3)
                p.drawText(QRectF(cx - slot * step / 2, plot.bottom() + 4, slot * step, fm.height()),
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, lbl)
        p.end()


class HBarList(QWidget):
    """Labelled horizontal bars (e.g. study time by subject, habit rates)."""

    ROW = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, float, str, str]] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def set_rows(self, rows: list[tuple[str, float, str, str]]) -> None:
        """rows: (label, fraction 0..1, value text, color key)."""
        self._rows = rows
        self.setFixedHeight(max(1, len(rows)) * self.ROW)
        self.setAccessibleDescription("; ".join(f"{r[0]}: {r[2]}" for r in rows))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont("Segoe UI")
        f.setPointSizeF(9.5)
        p.setFont(f)
        fm = p.fontMetrics()
        label_w = min(self.width() * 0.34, max((fm.horizontalAdvance(r[0]) for r in self._rows), default=0) + 12)
        value_w = max((fm.horizontalAdvance(r[2]) for r in self._rows), default=0) + 12
        track_w = max(20.0, self.width() - label_w - value_w)
        track_bg = theme.color("elevated") if theme.mode == "light" else theme.color("hover")
        for i, (lbl, frac, value_text, color_key) in enumerate(self._rows):
            y = i * self.ROW
            p.setPen(theme.color("text"))
            elided = fm.elidedText(lbl, Qt.TextElideMode.ElideRight, int(label_w - 10))
            p.drawText(QRectF(0, y, label_w, self.ROW), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
            track = QRectF(label_w, y + self.ROW / 2 - 4, track_w, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(track_bg)
            p.drawRoundedRect(track, 4, 4)
            if frac > 0:
                p.setBrush(theme.color(color_key))
                p.drawRoundedRect(QRectF(track.left(), track.top(), max(8.0, track.width() * min(1.0, frac)), 8), 4, 4)
            p.setPen(theme.color("text2"))
            p.drawText(QRectF(label_w + track_w, y, value_w, self.ROW),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value_text)
        p.end()


class LineChart(QWidget):
    """Percent scores over time (0–100 axis) with point markers."""

    def __init__(self, color_key: str = "blue", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[tuple[str, float, str]] = []
        self._color_key = color_key
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme.changed.connect(self.update)

    def set_points(self, points: list[tuple[str, float, str]]) -> None:
        """points: (x label, percent, tooltip) in chronological order."""
        self._points = points
        self.setAccessibleDescription("; ".join(pt[2] for pt in points[-12:]))
        self.update()

    def _plot(self) -> QRectF:
        fm = QFontMetrics(_small_font())
        left = fm.horizontalAdvance("100%") + 10
        return QRectF(left, 10, self.width() - left - 12, self.height() - 10 - fm.height() - 10)

    def _xy(self, i: int, value: float, plot: QRectF) -> QPointF:
        n = len(self._points)
        x = plot.left() + (plot.width() * (i / (n - 1)) if n > 1 else plot.width() / 2)
        y = plot.bottom() - plot.height() * max(0.0, min(100.0, value)) / 100
        return QPointF(x, y)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        plot = self._plot()
        for i, (_, value, tip) in enumerate(self._points):
            pt = self._xy(i, value, plot)
            if abs(pt.x() - event.position().x()) < 8 and abs(pt.y() - event.position().y()) < 12:
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(_small_font())
        fm = p.fontMetrics()
        plot = self._plot()
        for pct in (0, 50, 100):
            y = plot.bottom() - plot.height() * pct / 100
            p.setPen(QPen(theme.color("chart_grid"), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(theme.color("text3"))
            p.drawText(QRectF(0, y - fm.height() / 2, plot.left() - 6, fm.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{pct}%")
        if not self._points:
            p.end()
            return
        color = theme.color(self._color_key)
        pts = [self._xy(i, v, plot) for i, (_, v, _) in enumerate(self._points)]
        if len(pts) > 1:
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setPen(QPen(theme.color("surface"), 2))
        p.setBrush(color)
        for pt in pts:
            p.drawEllipse(pt, 4.5, 4.5)
        n = len(self._points)
        max_labels = max(1, int(plot.width() // (fm.horizontalAdvance("00 Mon") + 10)))
        step = max(1, math.ceil(n / max_labels))
        p.setPen(theme.color("text3"))
        for i, (lbl, _, _) in enumerate(self._points):
            if i % step == 0:
                x = pts[i].x()
                p.drawText(QRectF(x - 40, plot.bottom() + 4, 80, fm.height()), Qt.AlignmentFlag.AlignHCenter, lbl)
        p.end()


class ProgressRing(QWidget):
    """Circular progress used for the focus timer."""

    def __init__(self, size: int = 260, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fraction = 0.0
        self._color_key = "accent"
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        theme.changed.connect(self.update)

    def set_fraction(self, fraction: float, color_key: str = "accent") -> None:
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self._fraction) < 0.0005 and color_key == self._color_key:
            return
        self._fraction = fraction
        self._color_key = color_key
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 16
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        track = QPen(theme.color("elevated") if theme.mode == "light" else theme.color("hover"), 8)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawEllipse(rect)
        if self._fraction > 0:
            pen = QPen(theme.color(self._color_key), 8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, int(-360 * 16 * self._fraction))
        p.end()
