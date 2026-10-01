"""Theme gallery widgets: a painted miniature of each theme and accent swatches."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from src.ui import anim
from src.ui.anim import tween
from src.ui.theme import heading_font, sans, theme
from src.ui.themes import Theme


class ThemePreviewCard(QAbstractButton):
    """A selectable card showing a small, faithful sketch of a theme's layout and colours."""

    def __init__(self, preview: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preview = preview
        self.setCheckable(True)
        self._hover = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{preview.name} theme")
        self.setAccessibleDescription(preview.description)
        self.setToolTip(preview.description)
        self.setMinimumSize(220, 252)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, 252)

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
        t = self.preview.palette()
        c = lambda k: QColor(t[k])  # noqa: E731
        outer = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        radius = theme.shape.card_radius
        # card frame in the *current* app theme
        border = theme.color("accent") if self.isChecked() else theme.color("divider")
        if self._hover and not self.isChecked():
            border = theme.color("border")
        p.setPen(QPen(border, 2.2 if self.isChecked() else 1.2))
        p.setBrush(theme.color("surface"))
        p.drawRoundedRect(outer, radius, radius)
        if self.hasFocus():
            p.setPen(QPen(theme.color("focus"), 1.4, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(outer.adjusted(3, 3, -3, -3), radius - 2, radius - 2)
        # miniature window
        mini = QRectF(outer.x() + 12, outer.y() + 12, outer.width() - 24, 132)
        r = max(4.0, self.preview.shape.card_radius * 0.55)
        clip = QPainterPath()
        clip.addRoundedRect(mini, r, r)
        p.save()
        p.setClipPath(clip)
        p.fillRect(mini, c("bg"))
        side = QRectF(mini.x(), mini.y(), mini.width() * 0.26, mini.height())
        p.fillRect(side, c("sidebar"))
        p.setPen(Qt.PenStyle.NoPen)
        # brand dot + nav lines
        p.setBrush(c("accent"))
        p.drawEllipse(QRectF(side.x() + 8, side.y() + 9, 9, 9))
        for i in range(5):
            y = side.y() + 30 + i * 17
            if i == 0:
                p.setBrush(c("nav_pill"))
                p.drawRoundedRect(QRectF(side.x() + 5, y - 5, side.width() - 10, 15), 5, 5)
            p.setBrush(c("nav_active") if i == 0 else c("text3"))
            p.drawRoundedRect(QRectF(side.x() + 10, y, side.width() * (0.55 if i % 2 else 0.7), 4.5), 2, 2)
        # header text
        x0 = side.right() + 10
        p.setBrush(c("text"))
        p.drawRoundedRect(QRectF(x0, mini.y() + 12, mini.width() * 0.42, 7), 3, 3)
        p.setBrush(c("text2"))
        p.drawRoundedRect(QRectF(x0, mini.y() + 24, mini.width() * 0.3, 4.5), 2, 2)
        # banner
        p.setBrush(c("banner"))
        p.drawRoundedRect(QRectF(x0, mini.y() + 36, mini.right() - x0 - 10, 13), 4, 4)
        # two cards
        cw = (mini.right() - x0 - 10 - 7) / 2
        for k in range(2):
            card = QRectF(x0 + k * (cw + 7), mini.y() + 56, cw, mini.height() - 64)
            p.setBrush(c("surface"))
            p.setPen(QPen(c("divider"), 1))
            p.drawRoundedRect(card, r * 0.8, r * 0.8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("text"))
            p.drawRoundedRect(QRectF(card.x() + 7, card.y() + 8, card.width() * 0.5, 5), 2, 2)
            if k == 0:
                for j in range(3):
                    yy = card.y() + 21 + j * 12
                    p.setPen(QPen(c("accent") if j == 0 else c("text3"), 1.2))
                    p.setBrush(c("accent") if j == 0 else Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QRectF(card.x() + 7, yy - 1, 7, 7))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(c("text2"))
                    p.drawRoundedRect(QRectF(card.x() + 19, yy + 1, card.width() * 0.55, 3.5), 2, 2)
            else:
                p.setBrush(c("track"))
                p.drawRoundedRect(QRectF(card.x() + 7, card.y() + 22, card.width() - 14, 5), 2.5, 2.5)
                p.setBrush(c("progress"))
                p.drawRoundedRect(QRectF(card.x() + 7, card.y() + 22, (card.width() - 14) * 0.6, 5), 2.5, 2.5)
                p.setBrush(c("primary"))
                p.drawRoundedRect(QRectF(card.x() + 7, card.bottom() - 18, card.width() - 14, 11), 5, 5)
                p.setBrush(c("terracotta_soft"))
                p.drawRoundedRect(QRectF(card.x() + 7, card.y() + 33, 20, 7), 3.5, 3.5)
                p.setBrush(c("blue_soft"))
                p.drawRoundedRect(QRectF(card.x() + 30, card.y() + 33, 20, 7), 3.5, 3.5)
        p.restore()
        # name, description, swatches
        text_x = outer.x() + 14
        p.setPen(theme.color("text"))
        p.setFont(heading_font(12))
        p.drawText(QRectF(text_x, mini.bottom() + 8, outer.width() - 60, 24),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.preview.name)
        p.setPen(theme.color("text2"))
        p.setFont(sans(8.6))
        desc = QRectF(text_x, mini.bottom() + 32, outer.width() - 28, 52)
        p.drawText(desc, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   self.preview.description)
        x = outer.right() - 14
        for color in reversed(self.preview.swatches[:4]):
            x -= 13
            p.setPen(QPen(theme.color("border"), 1))
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(x, mini.bottom() + 14, 11, 11))
        if self.isChecked():
            badge = QRectF(outer.right() - 34, outer.y() + 18, 22, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("primary"))
            p.drawEllipse(badge)
            pen = QPen(theme.color("on_primary"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(badge.x() + 6.5, badge.y() + 11.5)
            path.lineTo(badge.x() + 9.8, badge.y() + 14.8)
            path.lineTo(badge.x() + 15.5, badge.y() + 7.8)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.end()


class AccentSwatch(QAbstractButton):
    """A round colour choice for the theme accent."""

    picked = Signal(str)

    def __init__(self, key: str, name: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.color = color
        self.setCheckable(True)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(name)
        self.setAccessibleName(f"{name} accent")
        self.clicked.connect(lambda: self.picked.emit(self.key))
        theme.changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        if self.isChecked() or self.hasFocus():
            p.setPen(QPen(theme.color("text") if self.isChecked() else theme.color("focus"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))
        p.setPen(QPen(theme.color("border"), 1))
        p.setBrush(QColor(self.color))
        p.drawEllipse(r)
        p.end()
