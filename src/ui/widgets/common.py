"""Reusable DayOS widgets built on the theme tokens and shared motion helpers."""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Callable, Iterable

from PySide6.QtCore import QDate, QPoint, QRect, QRectF, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.services.dates import ValidationError
from src.ui import anim
from src.ui.anim import tween
from src.ui.icons import bind_icon
from src.ui.theme import theme

log = logging.getLogger(__name__)
QWIDGETSIZE_MAX = 16777215


# -- small helpers -----------------------------------------------------------

def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def label(text: str = "", role: str | None = None, *, wrap: bool = False, selectable: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def chip(text: str, tone: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "chip")
    if tone:
        lbl.setProperty("tone", tone)
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lbl


def blend(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def mix(c1: str, c2: str, t: float) -> QColor:
    return blend(QColor(c1), QColor(c2), t)


# -- buttons -------------------------------------------------------------------

class AnimatedButton(QPushButton):
    """A push button that paints itself with smooth hover and press transitions.

    ``variant``: "" (outlined), "primary" (dark sage), "soft" (sage tint),
    "ghost", "danger", "link" or "segment" (used inside :class:`SegmentBar`).
    """

    _STYLES = {
        # variant: (background, hover background, pressed background, text, hover text, border)
        "": ("surface", "hover", "pressed", "text", "text", "border"),
        "primary": ("primary", "primary_hover", "primary_pressed", "on_primary", "on_primary", None),
        "soft": ("accent_soft", "pressed", "pressed", "accent_dark", "accent_dark", None),
        "ghost": (None, "hover", "pressed", "text2", "text", None),
        "danger": ("danger_soft", "danger_soft", "pressed", "danger", "danger", "danger_soft"),
        "link": (None, None, None, "accent_text", "accent_dark", None),
        "segment": (None, None, None, "text2", "text", None),
    }

    def __init__(self, text: str = "", variant: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("variant", variant)
        self._hover = 0.0
        self._press = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.pressed.connect(lambda: self._animate_press(1.0))
        self.released.connect(lambda: self._animate_press(0.0))
        theme.changed.connect(self.update)

    @property
    def variant(self) -> str:
        return str(self.property("variant") or "")

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

    def _set_press(self, v: float) -> None:
        self._press = v
        self.update()

    def _animate_press(self, target: float) -> None:
        tween(self, self._press, target, 90 if target else anim.FAST, self._set_press, key="_press_anim")

    def enterEvent(self, e) -> None:  # noqa: N802
        tween(self, self._hover, 1.0, anim.FAST, self._set_hover, key="_hover_anim")
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        tween(self, self._hover, 0.0, anim.FAST, self._set_hover, key="_hover_anim")
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        icon_w = self.iconSize().width() if not self.icon().isNull() else 0
        gap = 7 if text_w and icon_w else 0
        pad = 4 if self.variant == "link" else (12 if self.variant == "segment" else 15)
        menu = 16 if self.menu() is not None else 0
        height = fm.height() + 8 if self.variant == "link" else max(34, fm.height() + 16)
        width = text_w + icon_w + gap + pad * 2 + menu
        if not text_w:
            width = max(width, height)
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _colors(self) -> tuple[QColor | None, QColor, QColor | None]:
        t = theme.tokens
        bg, bg_h, bg_p, fg, fg_h, border = self._STYLES.get(self.variant, self._STYLES[""])
        if self.variant == "segment" and self.isChecked():
            parent = self.parentWidget()
            accent_style = parent is not None and parent.property("segstyle") == "accent"
            fg = fg_h = "on_primary" if accent_style else "text"
        hover = self._hover if self.isEnabled() else 0.0
        fill: QColor | None = None
        if bg or bg_h:
            target = QColor(t[bg_h]) if bg_h else QColor(t[bg])
            base = QColor(t[bg]) if bg else QColor(target.red(), target.green(), target.blue(), 0)
            fill = blend(base, target, hover)
            if bg_p and self._press:
                fill = blend(fill, QColor(t[bg_p]), self._press)
        text = blend(QColor(t[fg]), QColor(t[fg_h]), hover)
        edge = None
        if border:
            hover_edge = t["accent"] if self.variant == "" else t["danger"]
            edge = blend(QColor(t[border]), QColor(hover_edge), hover * 0.8)
        return fill, text, edge

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.5)
        fill, text_color, edge = self._colors()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = r.height() / 2 if self.property("round") else min(10.0, r.height() / 2)
        if (fill is not None and fill.alpha() > 0) or edge is not None:
            p.setPen(QPen(edge, 1) if edge is not None else Qt.PenStyle.NoPen)
            p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, radius, radius)
        if self.hasFocus() and getattr(self, "_kbd_focus", False):
            p.setPen(QPen(theme.color("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), max(0.0, radius - 1), max(0.0, radius - 1))
        fm = self.fontMetrics()
        text = self.text()
        icon_size = self.iconSize() if not self.icon().isNull() else QSize(0, 0)
        text_w = fm.horizontalAdvance(text) if text else 0
        gap = 7 if text and icon_size.width() else 0
        menu_w = 16 if self.menu() is not None else 0
        shift = 0.6 * self._press
        x = (self.width() - (icon_size.width() + gap + text_w + menu_w)) / 2
        if icon_size.width():
            mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
            state = QIcon.State.On if self.isChecked() else QIcon.State.Off
            pm = self.icon().pixmap(icon_size, mode, state)
            p.drawPixmap(QPoint(int(x), int((self.height() - icon_size.height()) / 2 + shift)), pm)
            x += icon_size.width() + gap
        if text:
            font = self.font()
            if self.property("serifSize"):
                from src.ui.theme import serif

                font = serif(float(self.property("serifSize")))
            if self.variant == "link":
                font.setUnderline(self._hover > 0.5)
            p.setFont(font)
            p.setPen(text_color)
            p.drawText(QRectF(x, shift, text_w + 2, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            x += text_w
        if menu_w:
            pen = QPen(text_color, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            cy = self.height() / 2
            path = QPainterPath()
            path.moveTo(x + 7, cy - 2)
            path.lineTo(x + 10, cy + 1.5)
            path.lineTo(x + 13, cy - 2)
            p.drawPath(path)
        p.end()


def button(
    text: str = "",
    variant: str = "",
    icon_name: str | None = None,
    on_click: Callable[[], None] | None = None,
    tooltip: str = "",
    icon_key: str | None = None,
) -> AnimatedButton:
    btn = AnimatedButton(text, variant)
    if icon_name:
        key = icon_key or {"primary": "on_primary", "danger": "danger", "soft": "accent_dark",
                           "link": "accent_text"}.get(variant, "text2")
        bind_icon(btn, icon_name, key, 16)
    if on_click:
        btn.clicked.connect(lambda _=False: on_click())
    if tooltip:
        btn.setToolTip(tooltip)
    if text or tooltip:
        btn.setAccessibleName(text or tooltip)
    return btn


def tool_button(icon_name: str, tooltip: str, on_click: Callable[[], None] | None = None, size: int = 18,
                color_key: str = "text2") -> QToolButton:
    btn = QToolButton()
    bind_icon(btn, icon_name, color_key, size)
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if on_click:
        btn.clicked.connect(lambda _=False: on_click())
    return btn


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("separator", True)
    line.setFixedHeight(1)
    return line


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def hbox(*widgets: QWidget | None, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0),
         stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if stretch_at == i:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        else:
            lay.addWidget(w)
    if stretch_at is not None and stretch_at >= len(widgets):
        lay.addStretch(1)
    return lay


def fit_list_items(list_widget) -> None:
    """Size QListWidget rows to their (polished) item widgets, honouring word wrap."""

    def fit() -> None:
        width = max(80, list_widget.viewport().width() - 4)
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            widget = list_widget.itemWidget(item)
            if widget is None:
                continue
            widget.ensurePolished()
            for child in widget.findChildren(QWidget):
                child.ensurePolished()
            lay = widget.layout()
            if lay is not None:
                lay.activate()
            height = widget.heightForWidth(width) if widget.hasHeightForWidth() else -1
            height = max(height, widget.sizeHint().height(), widget.minimumSizeHint().height()) + 2
            item.setSizeHint(QSize(width, height))

    fit()
    QTimer.singleShot(0, fit)


def scroll_wrap(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content.setObjectName("ScrollContent")
    area.setWidget(content)
    return area


def _icon_pixmap(name: str, key: str, size: int):
    from src.ui.icons import pixmap

    return pixmap(name, theme.tokens[key], size)


# -- structural widgets -----------------------------------------------------

class Card(QFrame):
    """A soft, rounded surface that lifts gently on hover.

    The card paints its own background and layered shadow (cheap, no blur
    effect), and can carry decorative artwork anchored to a corner behind the
    content via :meth:`set_art`.
    """

    RADIUS = 16.0
    INSET = (3, 2, 3, 6)  # room for the soft shadow

    def __init__(self, title: str = "", icon_name: str | None = None, parent: QWidget | None = None,
                 margins: int = 20) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._lift = 0.0
        self._art: QWidget | None = None
        self._art_corner = Qt.Corner.BottomRightCorner
        left, top, right, bottom = self.INSET
        outer = QVBoxLayout(self)
        outer.setContentsMargins(margins + left, margins - 2 + top, margins + right, margins + bottom - 2)
        outer.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        self.title_label: QLabel | None = None
        self._title_icon: tuple[QLabel, str] | None = None
        if title:
            if icon_name:
                ic = QLabel()
                ic.setPixmap(_icon_pixmap(icon_name, "text", 20))
                self._title_icon = (ic, icon_name)
                theme.changed.connect(self._refresh_title_icon)
                self.header.addWidget(ic)
            self.title_label = label(title, "section")
            self.header.addWidget(self.title_label)
            self.header.addStretch(1)
            outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)
        outer.addStretch(1)
        theme.changed.connect(self.update)

    def _refresh_title_icon(self) -> None:
        if self._title_icon:
            ic, name = self._title_icon
            ic.setPixmap(_icon_pixmap(name, "text", 20))

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget)

    def set_art(self, art: QWidget, corner: Qt.Corner = Qt.Corner.BottomRightCorner) -> None:
        art.setParent(self)
        art.lower()
        self._art = art
        self._art_corner = corner
        self._place_art()
        art.show()

    def _place_art(self) -> None:
        if self._art is None:
            return
        hint = self._art.sizeHint()
        left, top, right, bottom = self.INSET
        w, h = min(hint.width(), self.width() - left - right - 2), min(hint.height(), self.height() - top - bottom - 2)
        x = left + 1 if self._art_corner in (Qt.Corner.TopLeftCorner, Qt.Corner.BottomLeftCorner) else self.width() - right - 1 - w
        y = top + 1 if self._art_corner in (Qt.Corner.TopLeftCorner, Qt.Corner.TopRightCorner) else self.height() - bottom - 1 - h
        self._art.setGeometry(x, y, max(1, w), max(1, h))
        self._art.lower()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_art()

    def _set_lift(self, v: float) -> None:
        self._lift = v
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        tween(self, self._lift, 1.0, anim.MEDIUM, self._set_lift, key="_lift_anim")
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        tween(self, self._lift, 0.0, anim.MEDIUM, self._set_lift, key="_lift_anim")
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, right, bottom = self.INSET
        body = QRectF(self.rect()).adjusted(left, top, -right, -bottom)
        paint_card(p, body, self._lift, self.RADIUS)
        p.end()


def paint_card(p: QPainter, body: QRectF, lift: float = 0.0, radius: float = 16.0,
               fill_key: str = "surface") -> None:
    """Shared card painting: layered soft shadow, fill and hairline border."""
    shadow = theme.color("shadow")
    strength = 1.8 if theme.mode == "dark" else 1.0
    p.setPen(Qt.PenStyle.NoPen)
    for i, alpha in enumerate((0.045, 0.03, 0.018)):
        c = QColor(shadow)
        c.setAlphaF(min(1.0, alpha * strength * (1.0 + 0.9 * lift)))
        p.setBrush(c)
        grow = i + 0.5
        drop = 1.0 + i + 2.2 * lift
        p.drawRoundedRect(body.adjusted(-grow, -grow + drop, grow, grow + drop), radius + grow, radius + grow)
    p.setBrush(theme.color(fill_key))
    border = blend(theme.color("divider"), theme.color("accent"), 0.35 * lift)
    p.setPen(QPen(border, 1))
    p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class PageHeader(QWidget):
    """Eyebrow line, editorial serif title, supporting line and actions."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None, eyebrow: str = "") -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.eyebrow = label(eyebrow.upper(), "eyebrow")
        self.eyebrow.setVisible(bool(eyebrow))
        text.addWidget(self.eyebrow)
        self.title = label(title, "title")
        self.subtitle = label(subtitle, "subtitle", wrap=True)
        self.subtitle.setVisible(bool(subtitle))
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        lay.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)
        lay.setAlignment(self.actions, Qt.AlignmentFlag.AlignBottom)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def set_eyebrow(self, text: str) -> None:
        self.eyebrow.setText(text.upper())
        self.eyebrow.setVisible(bool(text))


class EmptyState(QWidget):
    """Friendly explanation plus working next-step actions; fades in when shown."""

    def __init__(self, icon_name: str, title: str, text: str,
                 actions: Iterable[tuple[str, Callable[[], None]]] = (), compact: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        pad = 8 if compact else 30
        lay.setContentsMargins(12, pad, 12, pad)
        lay.setSpacing(6)
        lay.addStretch(1)
        self._faded = False
        if compact:
            self._icon = QLabel()
            self._icon_name = icon_name
            self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._refresh()
            theme.changed.connect(self._refresh)
            lay.addWidget(self._icon)
        else:
            from src.ui.widgets.art import Art

            pot = Art("pot", 96, 88, Qt.AlignmentFlag.AlignCenter)
            pot.setFixedHeight(88)
            lay.addWidget(pot)
            lay.addSpacing(4)
        t = label(title, "heading" if compact else "section")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        if text:
            body = label(text, "muted", wrap=True)
            body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            lay.addWidget(body)
        acts = list(actions)
        if acts:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addStretch(1)
            for i, (text_, cb) in enumerate(acts):
                row.addWidget(button(text_, "primary" if i == 0 and not compact else "soft", on_click=cb))
            row.addStretch(1)
            lay.addSpacing(6)
            lay.addLayout(row)
        lay.addStretch(1)

    def _refresh(self) -> None:
        self._icon.setPixmap(_icon_pixmap(self._icon_name, "accent", 24))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._faded:
            self._faded = True
            anim.fade_in(self, anim.MEDIUM)


class ThinProgress(QWidget):
    """A slim rounded progress bar; value in [0, 1]. Changes glide smoothly."""

    def __init__(self, value: float = 0.0, color_key: str = "accent", height: int = 6,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self._shown = self._value
        self._color_key = color_key
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleDescription(f"{round(self._value * 100)} percent")
        theme.changed.connect(self.update)

    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self._value = value
        self.setAccessibleDescription(f"{round(value * 100)} percent")
        tween(self, self._shown, value, 380, self._set_shown, key="_progress_anim")

    def _set_shown(self, v: float) -> None:
        self._shown = v
        self.update()

    def set_color(self, key: str) -> None:
        self._color_key = key
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        radius = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color("elevated") if theme.mode == "light" else theme.color("hover"))
        p.drawRoundedRect(r, radius, radius)
        if self._shown > 0.001:
            fill = QRectF(r.x(), r.y(), max(r.height(), r.width() * self._shown), r.height())
            p.setBrush(theme.color(self._color_key))
            p.drawRoundedRect(fill, radius, radius)
        p.end()


class RoundCheck(QAbstractButton):
    """Circular completion toggle: the fill blooms and the tick draws itself in."""

    def __init__(self, checked: bool = False, size: int = 20, accessible_name: str = "Complete",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._size = size
        self._progress = 1.0 if checked else 0.0
        self._hover = 0.0
        self.setFixedSize(size + 6, size + 6)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(accessible_name)
        self.toggled.connect(self._on_toggled)
        theme.changed.connect(self.update)

    def _on_toggled(self, on: bool) -> None:
        tween(self, self._progress, 1.0 if on else 0.0, 220 if on else 140, self._set_progress, key="_check_anim")

    def _set_progress(self, v: float) -> None:
        self._progress = v
        self.update()

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        tween(self, self._hover, 1.0, anim.FAST, self._set_hover, key="_hover_anim")
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        tween(self, self._hover, 0.0, anim.FAST, self._set_hover, key="_hover_anim")
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._size + 6, self._size + 6)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        r = QRectF(3, 3, s, s)
        accent = theme.color("accent")
        prog = self._progress
        if self.hasFocus():
            p.setPen(QPen(theme.color("accent_dark"), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(-2.5, -2.5, 2.5, 2.5))
        ring = blend(theme.color("text3"), accent, max(self._hover, prog))
        soft = theme.color("accent_soft")
        soft.setAlphaF(self._hover * (1 - prog))
        p.setPen(QPen(ring, 1.6))
        p.setBrush(soft)
        p.drawEllipse(r.adjusted(0.8, 0.8, -0.8, -0.8))
        if prog > 0.01:
            grow = 0.35 + 0.65 * prog
            fill = QRectF(r.center().x() - s * grow / 2, r.center().y() - s * grow / 2, s * grow, s * grow)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawEllipse(fill)
        tick = (prog - 0.35) / 0.65
        if tick > 0:
            a = (3 + s * 0.28, 3 + s * 0.52)
            b = (3 + s * 0.44, 3 + s * 0.68)
            c = (3 + s * 0.73, 3 + s * 0.36)
            path = QPainterPath()
            path.moveTo(*a)
            first = min(1.0, tick / 0.4)
            path.lineTo(a[0] + (b[0] - a[0]) * first, a[1] + (b[1] - a[1]) * first)
            if tick > 0.4:
                second = (tick - 0.4) / 0.6
                path.lineTo(b[0] + (c[0] - b[0]) * second, b[1] + (c[1] - b[1]) * second)
            pen = QPen(theme.color("on_accent"), 1.9)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.end()


class SegmentBar(QFrame):
    """Segmented control with a selection pill that glides between options."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str | None = None,
                 parent: QWidget | None = None, style: str = "soft") -> None:
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        self.setProperty("segstyle", style)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, AnimatedButton] = {}
        self._pill = QRectF()
        for key, text in options:
            b = AnimatedButton(text, "segment")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._on_click(k))
            b.toggled.connect(lambda on, btn=b: on and self._move_pill(btn))
            self._group.addButton(b)
            self._buttons[key] = b
            lay.addWidget(b)
        self.set_current(current or options[0][0])
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def _on_click(self, key: str) -> None:
        self.changed.emit(key)

    def _move_pill(self, btn: AnimatedButton) -> None:
        target = QRectF(btn.geometry())
        if self._pill.isNull() or not self.isVisible():
            self._pill = target
            self.update()
            return
        start = QRectF(self._pill)

        def step(v: float) -> None:
            self._pill = QRectF(start.x() + (target.x() - start.x()) * v, target.y(),
                                start.width() + (target.width() - start.width()) * v, target.height())
            self.update()

        tween(self, 0.0, 1.0, anim.MEDIUM, step, key="_pill_anim")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        checked = self._group.checkedButton()
        if checked is not None:
            self._pill = QRectF(checked.geometry())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        checked = self._group.checkedButton()
        if checked is not None:
            self._pill = QRectF(checked.geometry())

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.color("divider"), 1))
        p.setBrush(theme.color("elevated"))
        p.drawRoundedRect(r, 12, 12)
        if not self._pill.isNull():
            if self.property("segstyle") == "accent":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("accent_dark") if theme.mode == "light" else theme.color("primary"))
            else:
                p.setPen(QPen(theme.color("border"), 1))
                p.setBrush(theme.color("surface"))
            p.drawRoundedRect(self._pill.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        p.end()

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def current(self) -> str:
        for key, b in self._buttons.items():
            if b.isChecked():
                return key
        return next(iter(self._buttons))

    def set_label(self, key: str, text: str) -> None:
        if key in self._buttons and self._buttons[key].text() != text:
            self._buttons[key].setText(text)
            self._buttons[key].updateGeometry()


class SearchField(QLineEdit):
    def __init__(self, placeholder: str = "Search", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._action = self.addAction(_search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        theme.changed.connect(self._refresh_icon)
        self.setAccessibleName(placeholder)
        self.setMinimumWidth(190)

    def _refresh_icon(self) -> None:
        self._action.setIcon(_search_icon())


def _search_icon():
    from src.ui.icons import icon

    return icon("search", "text3", 16)


class CollapsibleSection(QWidget):
    """A titled section whose content slides open and closed."""

    def __init__(self, title: str, expanded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.toggle = AnimatedButton(title, "ghost")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        bind_icon(self.toggle, "chev-down" if expanded else "chev-right", "text2", 14)
        self.toggle.clicked.connect(lambda: self.set_expanded(self.toggle.isChecked()))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.toggle)
        row.addStretch(1)
        lay.addLayout(row)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(4)
        lay.addWidget(self.content)
        self._expanded = expanded
        self.content.setMaximumHeight(QWIDGETSIZE_MAX if expanded else 0)

    def set_title(self, text: str) -> None:
        self.toggle.setText(text)
        self.toggle.updateGeometry()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.toggle.setChecked(expanded)
        bind_icon(self.toggle, "chev-down" if expanded else "chev-right", "text2", 14)
        full = self.content.sizeHint().height()
        start = self.content.height() if self.content.maximumHeight() else 0

        def step(v: float) -> None:
            self.content.setMaximumHeight(int(v))

        def done() -> None:
            self.content.setMaximumHeight(QWIDGETSIZE_MAX if self._expanded else 0)

        tween(self, start, full if expanded else 0, anim.MEDIUM, step, done, key="_collapse_anim")


class ResponsiveGrid(QWidget):
    """Lays out cards in 1–3 columns depending on the available width."""

    def __init__(self, breakpoints: tuple[int, int] = (760, 1500), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._items: list[tuple[QWidget, bool]] = []
        self._columns = 0
        self._breakpoints = breakpoints

    def add(self, widget: QWidget, wide: bool = False) -> None:
        self._items.append((widget, wide))
        self._relayout(force=True)

    def _column_count(self) -> int:
        w = self.width()
        if w < self._breakpoints[0]:
            return 1
        if w < self._breakpoints[1]:
            return 2
        return 3

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self, force: bool = False) -> None:
        cols = self._column_count()
        if cols == self._columns and not force:
            return
        self._columns = cols
        for widget, _ in self._items:
            self._grid.removeWidget(widget)
        for c in range(3):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        row, col = 0, 0
        for widget, wide in self._items:
            if wide:
                if col != 0:
                    row, col = row + 1, 0
                self._grid.addWidget(widget, row, 0, 1, cols)
                row += 1
                continue
            self._grid.addWidget(widget, row, col)
            col += 1
            if col >= cols:
                row, col = row + 1, 0
        self._grid.setRowStretch(row + 1, 1)


# -- form helpers ---------------------------------------------------------------

def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def from_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class DateEdit(QDateEdit):
    def __init__(self, value: date | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("ddd d MMM yyyy")
        self.setDate(to_qdate(value or date.today()))
        cal = self.calendarWidget()
        cal.setGridVisible(False)
        cal.setVerticalHeaderFormat(cal.VerticalHeaderFormat.NoVerticalHeader)
        self.setMinimumWidth(150)

    def value(self) -> date:
        return from_qdate(self.date())

    def set_value(self, d: date) -> None:
        self.setDate(to_qdate(d))

    def set_first_weekday(self, weekday: int) -> None:
        self.calendarWidget().setFirstDayOfWeek(Qt.DayOfWeek(weekday + 1))


class TimeEdit(QTimeEdit):
    def __init__(self, value: time | None = None, clock24: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDisplayFormat("HH:mm" if clock24 else "h:mm AP")
        v = value or time(9, 0)
        self.setTime(QTime(v.hour, v.minute))
        self.setMinimumWidth(90)

    def value(self) -> str:
        t = self.time()
        return f"{t.hour():02d}:{t.minute():02d}"

    def set_value(self, hhmm: str | None) -> None:
        if hhmm:
            h, m = hhmm.split(":")[:2]
            self.setTime(QTime(int(h), int(m)))


class OptionalDate(QWidget):
    """A checkbox that enables a date picker; value() returns None when unchecked."""

    toggled = Signal(bool)

    def __init__(self, text: str = "Set date", value: date | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox(text)
        self.edit = DateEdit(value or date.today())
        lay.addWidget(self.check)
        lay.addWidget(self.edit, 1)
        self.check.toggled.connect(self.edit.setEnabled)
        self.check.toggled.connect(self.toggled.emit)
        self.set_value(value)

    def value(self) -> date | None:
        return self.edit.value() if self.check.isChecked() else None

    def set_value(self, d: date | None) -> None:
        self.check.setChecked(d is not None)
        self.edit.setEnabled(d is not None)
        if d is not None:
            self.edit.set_value(d)


class OptionalTime(QWidget):
    def __init__(self, text: str = "Set time", value: str | None = None, clock24: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox(text)
        self.edit = TimeEdit(clock24=clock24)
        lay.addWidget(self.check)
        lay.addWidget(self.edit, 1)
        self.check.toggled.connect(self.edit.setEnabled)
        self.set_value(value)

    def value(self) -> str | None:
        return self.edit.value() if self.check.isChecked() else None

    def set_value(self, hhmm: str | None) -> None:
        self.check.setChecked(bool(hhmm))
        self.edit.setEnabled(bool(hhmm))
        if hhmm:
            self.edit.set_value(hhmm)


class IdCombo(QComboBox):
    """Combo box of (id, label) pairs with an optional 'none' entry."""

    def __init__(self, none_label: str | None = "None", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._none_label = none_label
        self.setMinimumWidth(160)

    def set_items(self, items: Iterable[tuple[int, str]], keep: bool = True) -> None:
        current = self.current_id() if keep else None
        self.blockSignals(True)
        self.clear()
        if self._none_label is not None:
            self.addItem(self._none_label, None)
        for item_id, text in items:
            self.addItem(text, item_id)
        self.blockSignals(False)
        self.set_current_id(current)

    def current_id(self) -> int | None:
        data = self.currentData()
        return int(data) if data is not None else None

    def set_current_id(self, item_id: int | None) -> None:
        index = self.findData(item_id) if item_id is not None else (0 if self._none_label is not None else -1)
        if index >= 0:
            self.setCurrentIndex(index)


# -- dialogs -------------------------------------------------------------------

class FadeDialog(QDialog):
    """Dialogs fade in when opened and out when closed (skipped with reduced motion)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._closing = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if anim.motion_enabled():
            self.setWindowOpacity(0.0)
            tween(self, 0.0, 1.0, 170, self.setWindowOpacity, key="_fade_anim")

    def done(self, result: int) -> None:  # noqa: D401 - Qt override
        if self._closing:
            return
        if not self.isVisible() or not anim.motion_enabled():
            super().done(result)
            return
        self._closing = True

        def finish() -> None:
            self._closing = False
            QDialog.done(self, result)
            self.setWindowOpacity(1.0)

        tween(self, self.windowOpacity(), 0.0, 120, self.setWindowOpacity, finish, key="_fade_anim")


class FormDialog(FadeDialog):
    """Base dialog: title, form rows, inline error text and Save/Cancel.

    Subclasses implement :meth:`save`, raising ValidationError for bad input.
    """

    def __init__(self, title: str, parent: QWidget | None = None, save_text: str = "Save",
                 width: int = 480) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 20)
        outer.setSpacing(16)
        outer.addWidget(label(title, "section"))
        self.form = QFormLayout()
        self.form.setSpacing(11)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addLayout(self.form)
        self.extra = QVBoxLayout()
        outer.addLayout(self.extra)
        self.error = label("", "danger", wrap=True)
        self.error.hide()
        outer.addWidget(self.error)
        buttons = QHBoxLayout()
        self.left_buttons = QHBoxLayout()
        buttons.addLayout(self.left_buttons)
        buttons.addStretch(1)
        self.cancel_btn = button("Cancel", "ghost", on_click=self.reject)
        self.save_btn = button(save_text, "primary", on_click=self._on_save)
        self.save_btn.setDefault(True)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.save_btn)
        outer.addLayout(buttons)

    def add_row(self, text: str, widget: QWidget | QLayout) -> None:
        self.form.addRow(text, widget)

    def show_error(self, message: str) -> None:
        was_hidden = self.error.isHidden()
        self.error.setText(message)
        self.error.show()
        if was_hidden:
            anim.fade_in(self.error, anim.FAST)

    def save(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def _on_save(self) -> None:
        try:
            self.save()
        except ValidationError as exc:
            self.show_error(str(exc))
            return
        except Exception as exc:  # database or unexpected failure: log, explain, keep dialog open
            log.exception("Saving failed in %s", type(self).__name__)
            self.show_error(f"Couldn't save: {exc}")
            return
        self.accept()


class MessageDialog(FadeDialog):
    def __init__(self, title: str, text: str, confirm_text: str = "OK", cancel_text: str | None = "Cancel",
                 danger: bool = False, parent: QWidget | None = None, detail: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setMaximumWidth(580)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(10)
        lay.addWidget(label(title, "section", wrap=True))
        body = label(text, "muted", wrap=True, selectable=True)
        lay.addWidget(body)
        if detail:
            lay.addWidget(label(detail, "caption", wrap=True, selectable=True))
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = None
        if cancel_text:
            cancel = button(cancel_text, "ghost", on_click=self.reject)
            row.addWidget(cancel)
        ok = button(confirm_text, "danger" if danger else "primary", on_click=self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        # Destructive confirmations default to the safe choice.
        default = cancel if (danger and cancel is not None) else ok
        default.setDefault(True)
        default.setFocus()


def confirm(parent: QWidget | None, title: str, text: str, confirm_text: str = "Delete",
            danger: bool = True) -> bool:
    return MessageDialog(title, text, confirm_text, "Cancel", danger, parent).exec() == QDialog.DialogCode.Accepted


def show_info(parent: QWidget | None, title: str, text: str, detail: str = "") -> None:
    MessageDialog(title, text, "OK", None, False, parent, detail).exec()


def show_error(parent: QWidget | None, title: str, text: str, detail: str = "") -> None:
    MessageDialog(title, text, "OK", None, False, parent, detail).exec()


def guarded(parent: QWidget | None, action: Callable[[], object], title: str = "Something went wrong") -> bool:
    """Run a UI action; show validation/database errors kindly instead of crashing."""
    try:
        action()
        return True
    except ValidationError as exc:
        show_error(parent, "Please check that", str(exc))
    except Exception as exc:
        log.exception("Action failed: %s", title)
        show_error(parent, title, f"{exc}", "Technical details were written to the DayOS log file.")
    return False


# -- toast ---------------------------------------------------------------------

class Toast(QFrame):
    """Brief confirmation that rises and fades in at the bottom, with an optional action."""

    def __init__(self, parent: QWidget, reduce_motion: Callable[[], bool] = lambda: False) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self._reduce_motion = reduce_motion
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 9, 9)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.text = QLabel()
        self.action_btn = AnimatedButton("", "soft")
        self.action_btn.clicked.connect(self._on_action)
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        lay.addWidget(self.action_btn)
        self._callback: Callable[[], None] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self.hide()

    def show_message(self, text: str, action: str | None = None, callback: Callable[[], None] | None = None,
                     ms: int = 5000) -> None:
        self.icon.setPixmap(_icon_pixmap("check", "on_primary", 16))
        self.text.setText(text)
        self._callback = callback
        self.action_btn.setVisible(bool(action))
        self.action_btn.setText(action or "")
        self.adjustSize()
        target = self._target_pos()
        self.show()
        self.raise_()
        if self._reduce_motion() or not anim.motion_enabled():
            self._effect.setOpacity(1.0)
            self.move(target)
        else:
            def step(v: float) -> None:
                self._effect.setOpacity(v)
                self.move(target.x(), int(target.y() + 14 * (1 - v)))

            tween(self, 0.0, 1.0, 190, step, key="_toast_anim")
        self._timer.start(ms)

    def _fade_out(self) -> None:
        if self._reduce_motion() or not anim.motion_enabled():
            self.hide()
            return
        tween(self, self._effect.opacity(), 0.0, anim.FAST, self._effect.setOpacity, self.hide, key="_toast_anim")

    def _target_pos(self) -> QPoint:
        parent = self.parentWidget()
        if parent is None:
            return self.pos()
        return QPoint(max(8, (parent.width() - self.width()) // 2), max(8, parent.height() - self.height() - 30))

    def _position(self) -> None:
        self.move(self._target_pos())

    def _on_action(self) -> None:
        callback = self._callback
        self._callback = None
        self.hide()
        if callback:
            callback()


def install_shortcut(widget: QWidget, keys: str, callback: Callable[[], None],
                     context: Qt.ShortcutContext = Qt.ShortcutContext.WidgetWithChildrenShortcut) -> QShortcut:
    sc = QShortcut(QKeySequence(keys), widget)
    sc.setContext(context)
    sc.activated.connect(callback)
    return sc


def colored_dot(color: str, size: int = 8) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet(f"background: {color}; border-radius: {size // 2}px;")
    return lbl


__all__ = [
    "AnimatedButton", "Card", "CollapsibleSection", "DateEdit", "EmptyState", "FadeDialog", "FormDialog",
    "IdCombo", "MessageDialog", "OptionalDate", "OptionalTime", "PageHeader", "QRect", "ResponsiveGrid",
    "RoundCheck", "SearchField", "SegmentBar", "ThinProgress", "TimeEdit", "Toast", "blend", "button", "chip",
    "clear_layout", "colored_dot", "confirm", "fit_list_items", "from_qdate", "guarded", "hbox",
    "install_shortcut", "label", "mix", "paint_card", "repolish", "scroll_wrap", "separator", "show_error",
    "show_info", "to_qdate", "tool_button",
]
