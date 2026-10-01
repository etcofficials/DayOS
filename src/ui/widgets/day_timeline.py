"""A painted day timeline: hour rows with timed items as blocks; overlapping items sit side by side."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from src.models import AgendaItem
from src.services.dates import format_time
from src.ui.theme import KIND_COLORS, sans, theme
from src.ui.widgets.common import blend

HOUR_PX = 52
GUTTER = 62


def _mins(hhmm: str) -> int:
    h, m = (int(x) for x in hhmm.split(":")[:2])
    return h * 60 + m


def layout_columns(items: list[AgendaItem]) -> list[tuple[AgendaItem, int, int]]:
    """Assign overlapping timed items to columns: returns (item, column, columns in its cluster)."""
    timed = sorted((i for i in items if i.start_time), key=lambda i: (i.start_time, i.end_time or ""))
    placed: list[tuple[AgendaItem, int, int]] = []
    cluster: list[tuple[AgendaItem, int]] = []
    cluster_end = -1
    columns_end: list[int] = []

    def flush() -> None:
        width = max((c for _, c in cluster), default=-1) + 1
        placed.extend((it, col, width) for it, col in cluster)

    for item in timed:
        start = _mins(item.start_time)  # type: ignore[arg-type]
        end = _mins(item.end_time) if item.end_time else start + 30
        if start >= cluster_end and cluster:
            flush()
            cluster, columns_end = [], []
        for col, col_end in enumerate(columns_end):
            if col_end <= start:
                columns_end[col] = end
                cluster.append((item, col))
                break
        else:
            columns_end.append(end)
            cluster.append((item, len(columns_end) - 1))
        cluster_end = max(cluster_end, end)
    if cluster:
        flush()
    return placed


class DayTimeline(QWidget):
    item_clicked = Signal(object, object)  # AgendaItem, global QPoint
    slot_activated = Signal(str)  # "HH:MM"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items: list[AgendaItem] = []
        self.clock24 = True
        self.first_hour, self.last_hour = 7, 22
        self.now_minutes: int | None = None
        self._rects: list[tuple[QRectF, AgendaItem]] = []
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Day timeline")
        theme.changed.connect(self.update)

    def set_items(self, items: list[AgendaItem], clock24: bool, now_minutes: int | None) -> None:
        self.items = [i for i in items if i.start_time]
        self.clock24 = clock24
        self.now_minutes = now_minutes
        hours = [_mins(i.start_time) // 60 for i in self.items] + [(_mins(i.end_time) + 59) // 60
                                                                     for i in self.items if i.end_time]
        self.first_hour = min([7] + hours)
        self.last_hour = max([22] + hours)
        self.setFixedHeight((self.last_hour - self.first_hour) * HOUR_PX + 24)
        self.setAccessibleDescription("; ".join(f"{i.start_time} {i.title}" for i in self.items) or "No timed items")
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(500, (self.last_hour - self.first_hour) * HOUR_PX + 24)

    def _y(self, minutes: int) -> float:
        return 12 + (minutes - self.first_hour * 60) * HOUR_PX / 60

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(sans(8.5))
        grid = theme.color("chart_grid")
        for h in range(self.first_hour, self.last_hour + 1):
            y = self._y(h * 60)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(GUTTER, y), QPointF(self.width() - 4, y))
            p.setPen(theme.color("text3"))
            p.drawText(QRectF(0, y - 9, GUTTER - 10, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       format_time(f"{h % 24:02d}:00", self.clock24))
        self._rects = []
        width = self.width() - GUTTER - 10
        for item, col, cols in layout_columns(self.items):
            start = _mins(item.start_time)  # type: ignore[arg-type]
            end = _mins(item.end_time) if item.end_time else start + 30
            cw = width / cols
            r = QRectF(GUTTER + 4 + col * cw, self._y(start) + 1, cw - 6, max(20.0, self._y(end) - self._y(start) - 2))
            color = theme.color(KIND_COLORS.get(item.kind, "accent"))
            fill = blend(theme.color("surface"), color, 0.22 if theme.mode == "light" else 0.32)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, 7, 7)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(r.x(), r.y(), 4, r.height()), 2, 2)
            if cols > 1:
                p.setPen(QPen(theme.color("amber"), 1.2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r, 7, 7)
            p.setPen(theme.color("text"))
            p.setFont(sans(9.5, QFont.Weight.DemiBold))
            fm = QFontMetrics(p.font())
            text_r = r.adjusted(10, 3, -6, -3)
            p.drawText(text_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       fm.elidedText(item.title, Qt.TextElideMode.ElideRight, int(text_r.width())))
            if r.height() > 36:
                p.setFont(sans(8.5))
                p.setPen(theme.color("text2"))
                when = format_time(item.start_time, self.clock24) + (
                    f"–{format_time(item.end_time, self.clock24)}" if item.end_time else "")
                p.drawText(text_r.adjusted(0, 17, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                           when + (" · overlaps" if cols > 1 else ""))
            self._rects.append((r, item))
        if self.now_minutes is not None and self.first_hour * 60 <= self.now_minutes <= self.last_hour * 60:
            y = self._y(self.now_minutes)
            p.setPen(QPen(theme.color("terracotta"), 1.6))
            p.drawLine(QPointF(GUTTER - 4, y), QPointF(self.width() - 4, y))
            p.setBrush(theme.color("terracotta"))
            p.drawEllipse(QPointF(GUTTER - 4, y), 3.5, 3.5)
        p.end()

    def _item_at(self, pos) -> AgendaItem | None:
        for rect, item in reversed(self._rects):
            if rect.contains(QPointF(pos)):
                return item
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        item = self._item_at(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if item else Qt.CursorShape.ArrowCursor)
        if item:
            QToolTip.showText(event.globalPosition().toPoint(), f"{item.title}\n{item.detail}".strip(), self)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        item = self._item_at(event.position())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            self.item_clicked.emit(item, event.globalPosition().toPoint())
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._item_at(event.position()) is None:
            minutes = self.first_hour * 60 + (event.position().y() - 12) * 60 / HOUR_PX
            minutes = max(0, min(23 * 60 + 30, int(minutes // 30 * 30)))
            self.slot_activated.emit(f"{minutes // 60:02d}:{minutes % 60:02d}")
