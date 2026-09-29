"""Reusable DayOS widgets built on the theme tokens."""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Callable, Iterable

from PySide6.QtCore import QDate, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
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
from src.ui.icons import bind_icon
from src.ui.theme import theme

log = logging.getLogger(__name__)


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


def button(
    text: str = "",
    variant: str = "",
    icon_name: str | None = None,
    on_click: Callable[[], None] | None = None,
    tooltip: str = "",
    icon_key: str | None = None,
) -> QPushButton:
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if icon_name:
        key = icon_key or ("on_accent" if variant == "primary" else "danger" if variant == "danger" else "text2")
        bind_icon(btn, icon_name, key, 16)
    if on_click:
        btn.clicked.connect(lambda _=False: on_click())
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def tool_button(icon_name: str, tooltip: str, on_click: Callable[[], None] | None = None, size: int = 18,
                color_key: str = "text2") -> QToolButton:
    btn = QToolButton()
    bind_icon(btn, icon_name, color_key, size)
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
            if height <= 0:
                height = widget.sizeHint().height()
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


# -- structural widgets -----------------------------------------------------

class Card(QFrame):
    """A calm surface with an optional header row (title + actions)."""

    def __init__(self, title: str = "", icon_name: str | None = None, parent: QWidget | None = None,
                 margins: int = 18) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(margins, margins - 2, margins, margins)
        outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(6)
        self.title_label: QLabel | None = None
        if title:
            if icon_name:
                ic = QLabel()
                ic.setPixmap(_icon_pixmap(icon_name, "accent", 16))
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

    def _refresh_title_icon(self) -> None:
        ic, name = self._title_icon
        ic.setPixmap(_icon_pixmap(name, "accent", 16))

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget)


def _icon_pixmap(name: str, key: str, size: int):
    from src.ui.icons import pixmap

    return pixmap(name, theme.tokens[key], size)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(title, "title")
        self.subtitle = label(subtitle, "subtitle", wrap=True)
        text.addWidget(self.title)
        if subtitle:
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


class EmptyState(QWidget):
    """Friendly explanation plus working next-step actions."""

    def __init__(self, icon_name: str, title: str, text: str,
                 actions: Iterable[tuple[str, Callable[[], None]]] = (), compact: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        pad = 10 if compact else 36
        lay.setContentsMargins(12, pad, 12, pad)
        lay.setSpacing(6)
        lay.addStretch(1)
        self._icon = QLabel()
        self._icon_name = icon_name
        self._size = 22 if compact else 34
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh()
        theme.changed.connect(self._refresh)
        lay.addWidget(self._icon)
        t = label(title, "section")
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
                row.addWidget(button(text_, "primary" if i == 0 else "", on_click=cb))
            row.addStretch(1)
            lay.addSpacing(6)
            lay.addLayout(row)
        lay.addStretch(1)

    def _refresh(self) -> None:
        self._icon.setPixmap(_icon_pixmap(self._icon_name, "text3", self._size))


class ThinProgress(QWidget):
    """A slim rounded progress bar; value in [0, 1]."""

    def __init__(self, value: float = 0.0, color_key: str = "accent", height: int = 6,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = value
        self._color_key = color_key
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self.setAccessibleDescription(f"{round(self._value * 100)} percent")
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
        if self._value > 0:
            fill = QRectF(r.x(), r.y(), max(r.height(), r.width() * self._value), r.height())
            p.setBrush(theme.color(self._color_key))
            p.drawRoundedRect(fill, radius, radius)
        p.end()


class RoundCheck(QAbstractButton):
    """Circular completion toggle used for tasks, habits and checklists."""

    def __init__(self, checked: bool = False, size: int = 20, accessible_name: str = "Complete",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._size = size
        self.setFixedSize(size + 6, size + 6)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(accessible_name)
        self._hover = False
        theme.changed.connect(self.update)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._size + 6, self._size + 6)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(3, 3, self._size, self._size)
        accent = theme.color("accent")
        if self.hasFocus():
            p.setPen(QPen(accent, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(-2.5, -2.5, 2.5, 2.5))
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawEllipse(r)
            pen = QPen(theme.color("on_accent"), 1.9)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            s = self._size
            path = QPainterPath()
            path.moveTo(3 + s * 0.28, 3 + s * 0.52)
            path.lineTo(3 + s * 0.44, 3 + s * 0.68)
            path.lineTo(3 + s * 0.73, 3 + s * 0.36)
            p.drawPath(path)
        else:
            color = accent if self._hover else theme.color("text3")
            p.setPen(QPen(color, 1.6))
            p.setBrush(theme.color("accent_soft") if self._hover else Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(0.8, 0.8, -0.8, -0.8))
        p.end()


class SegmentBar(QFrame):
    """A compact segmented control; emits the selected key."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setProperty("segment", True)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self._group.addButton(b)
            self._buttons[key] = b
            lay.addWidget(b)
        self.set_current(current or options[0][0])
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def current(self) -> str:
        for key, b in self._buttons.items():
            if b.isChecked():
                return key
        return next(iter(self._buttons))

    def set_label(self, key: str, text: str) -> None:
        if key in self._buttons:
            self._buttons[key].setText(text)


class SearchField(QLineEdit):
    def __init__(self, placeholder: str = "Search", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._action = self.addAction(_search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        theme.changed.connect(self._refresh_icon)
        self.setAccessibleName(placeholder)
        self.setMinimumWidth(180)

    def _refresh_icon(self) -> None:
        self._action.setIcon(_search_icon())


def _search_icon():
    from src.ui.icons import icon

    return icon("search", "text3", 16)


class ResponsiveGrid(QWidget):
    """Lays out cards in 1–3 columns depending on the available width."""

    def __init__(self, breakpoints: tuple[int, int] = (760, 1500), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(16)
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
        # Masonry-light: fill columns left to right, wide items take a full row.
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

class FormDialog(QDialog):
    """Base dialog: title, form rows, inline error text and Save/Cancel.

    Subclasses implement :meth:`save`, raising ValidationError for bad input.
    """

    def __init__(self, title: str, parent: QWidget | None = None, save_text: str = "Save",
                 width: int = 460) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(14)
        outer.addWidget(label(title, "section"))
        self.form = QFormLayout()
        self.form.setSpacing(10)
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
        if isinstance(widget, QLayout):
            self.form.addRow(text, widget)
        else:
            self.form.addRow(text, widget)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

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


class MessageDialog(QDialog):
    def __init__(self, title: str, text: str, confirm_text: str = "OK", cancel_text: str | None = "Cancel",
                 danger: bool = False, parent: QWidget | None = None, detail: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setMaximumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label(title, "section", wrap=True))
        body = label(text, "muted", wrap=True, selectable=True)
        lay.addWidget(body)
        if detail:
            lay.addWidget(label(detail, "caption", wrap=True, selectable=True))
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        if cancel_text:
            cancel = button(cancel_text, "ghost", on_click=self.reject)
            row.addWidget(cancel)
        ok = button(confirm_text, "danger" if danger else "primary", on_click=self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        # Destructive confirmations default to the safe choice.
        (cancel if (danger and cancel_text) else ok).setDefault(True)
        (cancel if (danger and cancel_text) else ok).setFocus()


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
    """Brief bottom-center message with an optional action (e.g. Undo)."""

    def __init__(self, parent: QWidget, reduce_motion: Callable[[], bool] = lambda: False) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self._reduce_motion = reduce_motion
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 8, 8)
        lay.setSpacing(12)
        self.text = QLabel()
        self.action_btn = QPushButton()
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.clicked.connect(self._on_action)
        lay.addWidget(self.text)
        lay.addWidget(self.action_btn)
        self._callback: Callable[[], None] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hide()

    def show_message(self, text: str, action: str | None = None, callback: Callable[[], None] | None = None,
                     ms: int = 5000) -> None:
        self.text.setText(text)
        self._callback = callback
        self.action_btn.setVisible(bool(action))
        self.action_btn.setText(action or "")
        self.adjustSize()
        self._position()
        self.show()
        self.raise_()
        if not self._reduce_motion():
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._effect.setOpacity(1.0)
        self._timer.start(ms)

    def _position(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 28
        self.move(max(8, x), max(8, y))

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


def mix(c1: str, c2: str, t: float) -> QColor:
    a, b = QColor(c1), QColor(c2)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )
