"""Sidebar navigation: serif nav items and a selection pill that glides between them."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from src.ui import anim
from src.ui.anim import tween
from src.ui.icons import pixmap
from src.ui.theme import serif, theme
from src.ui.widgets.common import blend


class NavItem(QAbstractButton):
    """A checkable navigation entry: line icon plus serif label (icon only when collapsed)."""

    HEIGHT = 46

    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.icon_name = icon_name
        self.setCheckable(True)
        self.collapsed = False
        self._hover = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.HEIGHT)
        self.setAccessibleName(text)
        self.setFont(serif(12.5))
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, self.HEIGHT)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self._kbd_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                             Qt.FocusReason.ShortcutFocusReason)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._kbd_focus = False
        self.update()
        super().focusOutEvent(event)

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        tween(self, self._hover, 1.0, anim.FAST, self._set_hover, key="_hover_anim")
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        tween(self, self._hover, 0.0, anim.FAST, self._set_hover, key="_hover_anim")
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -1.5)
        if self._hover > 0 and not self.isChecked():
            hover = theme.color("accent_soft")
            hover.setAlphaF(0.45 * self._hover)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(hover)
            p.drawRoundedRect(r, 12, 12)
        if self.hasFocus() and getattr(self, "_kbd_focus", False):
            p.setPen(QPen(theme.color("accent"), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 11, 11)
        active = self.isChecked()
        color = theme.tokens["accent_dark" if theme.mode == "light" else "text"] if active else theme.tokens["text"]
        icon_px = pixmap(self.icon_name, color if active else theme.tokens["text2"], 21)
        x = (self.width() - 21) // 2 if self.collapsed else 16
        p.drawPixmap(QPoint(x, (self.height() - 21) // 2), icon_px)
        if not self.collapsed:
            text_color = blend(theme.color("text2"), theme.color("text"), max(self._hover, 1.0 if active else 0.0))
            p.setPen(text_color)
            p.setFont(serif(12.5))
            p.drawText(QRectF(50, 0, self.width() - 56, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()


class Sidebar(QWidget):
    """Paints the sidebar background and the gliding selection pill behind the active item."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._pill = QRectF()
        self._target: NavItem | None = None
        theme.changed.connect(self.update)

    def _item_rect(self, item: NavItem) -> QRectF:
        top_left = item.mapTo(self, QPoint(0, 0))
        return QRectF(top_left.x(), top_left.y() + 1.5, item.width(), item.height() - 3)

    def select(self, item: NavItem, animate: bool = True) -> None:
        self._target = item
        target = self._item_rect(item)
        if not animate or self._pill.isNull() or not self.isVisible():
            self._pill = target
            self.update()
            return
        start = QRectF(self._pill)

        def step(v: float) -> None:
            self._pill = QRectF(start.x() + (target.x() - start.x()) * v, start.y() + (target.y() - start.y()) * v,
                                start.width() + (target.width() - start.width()) * v, target.height())
            self.update()

        tween(self, 0.0, 1.0, 230, step, key="_pill_anim")

    def resync(self) -> None:
        """Snap the pill to the active item after layout changes (resize, collapse)."""
        if self._target is not None:
            self._pill = self._item_rect(self._target)
            self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resync()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), theme.color("sidebar"))
        p.setPen(QPen(theme.color("divider"), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        if not self._pill.isNull():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("accent_soft"))
            p.drawRoundedRect(self._pill, 12, 12)
        p.end()
