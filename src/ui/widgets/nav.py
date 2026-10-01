"""Sidebar navigation: grouped nav items in a scrollable list, with a selection pill that glides between them."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from src.ui import anim
from src.ui.anim import tween
from src.ui.icons import pixmap
from src.ui.theme import nav_font, theme
from src.ui.widgets.common import blend


class NavItem(QAbstractButton):
    """A checkable navigation entry: line icon plus label (icon only when collapsed)."""

    HEIGHT = 40

    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.icon_name = icon_name
        self.setCheckable(True)
        self.collapsed = False
        self.badge = ""
        self._hover = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.HEIGHT)
        self.setAccessibleName(text)
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, self.HEIGHT)

    def set_badge(self, text: str) -> None:
        if text != self.badge:
            self.badge = text
            self.setAccessibleDescription(text)
            self.update()

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
        radius = theme.shape.pill_radius
        if self._hover > 0 and not self.isChecked():
            hover = theme.color("nav_pill")
            hover.setAlphaF(0.5 * self._hover)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(hover)
            p.drawRoundedRect(r, radius, radius)
        if self.hasFocus() and getattr(self, "_kbd_focus", False):
            p.setPen(QPen(theme.color("focus"), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        active = self.isChecked()
        icon_px = pixmap(self.icon_name, theme.tokens["nav_active"] if active else theme.tokens["text2"], 19)
        x = (self.width() - 19) // 2 if self.collapsed else 14
        p.drawPixmap(QPoint(x, (self.height() - 19) // 2), icon_px)
        if self.badge:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("terracotta"))
            if self.collapsed:
                p.drawEllipse(QRectF(x + 15, (self.height() - 19) / 2 - 2, 7, 7))
        if not self.collapsed:
            text_color = blend(theme.color("text2"), theme.color("text"), max(self._hover, 1.0 if active else 0.0))
            p.setPen(text_color)
            p.setFont(nav_font())
            right = 10
            if self.badge:
                fm = p.fontMetrics()
                bw = max(20, fm.horizontalAdvance(self.badge) + 12)
                badge = QRectF(self.width() - bw - 8, (self.height() - 18) / 2, bw, 18)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("terracotta_soft"))
                p.drawRoundedRect(badge, 9, 9)
                p.setPen(theme.color("terracotta_text"))
                font = p.font()
                font.setPointSizeF(max(7.5, font.pointSizeF() * 0.72))
                p.setFont(font)
                p.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.badge)
                p.setFont(nav_font())
                p.setPen(text_color)
                right = int(bw + 14)
            p.drawText(QRectF(44, 0, self.width() - 44 - right, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width() - 44 - right))
        p.end()


class NavGroupLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.full = text.upper()
        self.setObjectName("NavGroup")
        self.setFixedHeight(26)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)


class NavList(QWidget):
    """Holds nav items and group labels and paints the gliding selection pill behind them."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavList")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(2)
        self._pill = QRectF()
        self._target: NavItem | None = None
        self._groups: list[NavGroupLabel] = []
        self.collapsed = False
        theme.changed.connect(self.update)

    def add_group(self, text: str) -> NavGroupLabel:
        lbl = NavGroupLabel(text)
        self._groups.append(lbl)
        self.lay.addWidget(lbl)
        return lbl

    def add_item(self, item: NavItem) -> None:
        self.lay.addWidget(item)

    def finish(self) -> None:
        self.lay.addStretch(1)

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        for g in self._groups:
            g.setText("" if collapsed else g.full)
            g.setFixedHeight(10 if collapsed else 26)
            g.setVisible(True)

    def _item_rect(self, item: NavItem) -> QRectF:
        top_left = item.mapTo(self, QPoint(0, 0))
        return QRectF(top_left.x(), top_left.y() + 1.5, item.width(), item.height() - 3)

    def select(self, item: NavItem | None, animate: bool = True) -> None:
        self._target = item
        if item is None or not item.isVisible():
            self._pill = QRectF()
            self.update()
            return
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
        if self._target is not None and self._target.isVisible():
            self._pill = self._item_rect(self._target)
        else:
            self._pill = QRectF()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resync()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._pill.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color("nav_pill"))
        radius = theme.shape.pill_radius
        p.drawRoundedRect(self._pill, radius, radius)
        p.end()

    def content_height(self) -> int:
        return self.lay.sizeHint().height()


class Sidebar(QWidget):
    """Paints the sidebar background and divider; hosts the scrollable nav list."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.nav = NavList()
        self.scroll = QScrollArea()
        self.scroll.setObjectName("NavScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea#NavScroll, QScrollArea#NavScroll > QWidget > QWidget { background: transparent; }")
        self.scroll.setWidget(self.nav)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self._place_art())
        self.art: QWidget | None = None
        theme.changed.connect(self.update)

    # Compatibility with the v1 API used by the main window and tests.
    def select(self, item: NavItem, animate: bool = True) -> None:
        self.nav.select(item, animate)
        self.ensure_visible(item)

    def ensure_visible(self, item: NavItem) -> None:
        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(item, 0, 24) if item.isVisible() else None)

    def resync(self) -> None:
        self.nav.resync()
        self._place_art()

    @property
    def _pill(self) -> QRectF:  # used by tests
        return self.nav._pill

    def set_art(self, art: QWidget) -> None:
        self.art = art
        art.setParent(self)
        art.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._place_art()

    def _place_art(self) -> None:
        """Show decorative art only in the free space below the last nav item."""
        if self.art is None:
            return
        viewport = self.scroll.viewport()
        top_in_side = viewport.mapTo(self, QPoint(0, 0)).y()
        used = self.nav.content_height() - self.scroll.verticalScrollBar().value()
        free = viewport.height() - used
        if free < 150 or getattr(self, "collapsed", False):
            self.art.hide()
            return
        height = min(free - 8, 250)
        self.art.setGeometry(0, top_in_side + viewport.height() - height, self.width() - 1, height)
        self.art.show()
        self.art.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(0, self.resync)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), theme.color("sidebar"))
        p.setPen(QPen(theme.color("divider"), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.end()
