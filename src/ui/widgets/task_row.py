"""A single task line used by the Tasks page and the Today dashboard."""

from __future__ import annotations

from datetime import date
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.models import Task
from src.services.dates import format_date, format_duration, format_time, relative_day
from src.ui.widgets.common import RoundCheck, chip, label, repolish, tool_button


class TaskRow(QWidget):
    toggled = Signal(int, bool)
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    menu_requested = Signal(int, object)

    def __init__(self, task: Task, today: date, *, clock24: bool = True, date_style: str = "dmy",
                 compact: bool = False, show_actions: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task = task
        self.setObjectName("Row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5 if compact else 7, 6, 5 if compact else 7)
        lay.setSpacing(10)

        self.check = RoundCheck(task.done, 18 if compact else 20, f"Complete task: {task.title}")
        self.check.toggled.connect(lambda on: self.toggled.emit(task.id, on))
        lay.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(task.title)
        title.setWordWrap(True)
        title.setProperty("role", "rowtitle")
        if task.done:
            title.setProperty("strike", "true")
        text.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(6)
        items = self._meta(task, today, clock24, date_style, compact)
        for w in items:
            meta.addWidget(w)
        meta.addStretch(1)
        if items:
            text.addLayout(meta)
        lay.addLayout(text, 1)

        self.actions = QWidget()
        act = QHBoxLayout(self.actions)
        act.setContentsMargins(0, 0, 0, 0)
        act.setSpacing(2)
        act.addWidget(tool_button("edit", "Edit task", lambda: self.edit_requested.emit(task.id), 16))
        act.addWidget(tool_button("trash", "Delete task", lambda: self.delete_requested.emit(task.id), 16))
        lay.addWidget(self.actions, 0, Qt.AlignmentFlag.AlignTop)
        self.actions.setVisible(False)
        self._show_actions = show_actions
        self.setToolTip(task.description[:300] if task.description else "")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Task: {task.title}" + (" (completed)" if task.done else ""))

    @staticmethod
    def _meta(task: Task, today: date, clock24: bool, date_style: str, compact: bool) -> list[QWidget]:
        out: list[QWidget] = []
        if task.due:
            when = relative_day(task.due, today)
            if abs((task.due - today).days) >= 7:
                when = format_date(task.due, date_style)
            if task.due_time:
                when += f" · {format_time(task.due_time, clock24)}"
            if task.is_overdue(today):
                out.append(chip(f"Overdue · {when}", "danger"))
            else:
                out.append(label(when, "caption"))
        if task.priority == 2 and not task.done:
            out.append(chip("High priority", "terracotta"))
        elif task.priority == 0 and not compact:
            out.append(chip("Low", ""))
        if task.subject_name:
            out.append(chip(task.subject_name, "blue"))
        if task.category and not compact:
            out.append(chip(task.category, ""))
        if task.subtask_total:
            out.append(label(f"Checklist {task.subtask_done}/{task.subtask_total}", "caption"))
        if task.estimate_minutes and not compact:
            out.append(label(f"~{format_duration(task.estimate_minutes * 60)}", "caption"))
        if task.goal_title and not compact:
            out.append(label(f"Goal: {task.goal_title}", "caption"))
        return out

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        repolish(self)
        if self._show_actions:
            self.actions.setVisible(selected or self.underMouse())

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._show_actions:
            self.actions.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._show_actions and self.property("selected") != "true":
            self.actions.setVisible(False)
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.edit_requested.emit(self.task.id)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.menu_requested.emit(self.task.id, event.globalPos())

    def focusInEvent(self, event) -> None:  # noqa: N802
        self.set_selected(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.set_selected(False)
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.check.click()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.edit_requested.emit(self.task.id)
        elif key == Qt.Key.Key_Delete:
            self.delete_requested.emit(self.task.id)
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self._move_focus(1 if key == Qt.Key.Key_Down else -1)
        else:
            super().keyPressEvent(event)

    def _move_focus(self, step: int) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        rows = [w for w in parent.findChildren(TaskRow, options=Qt.FindChildOption.FindDirectChildrenOnly) if w.isVisible()]
        rows.sort(key=lambda w: w.y())
        if self in rows:
            i = rows.index(self) + step
            if 0 <= i < len(rows):
                rows[i].setFocus(Qt.FocusReason.TabFocusReason)


def connect_row(row: TaskRow, on_toggle: Callable[[int, bool], None], on_edit: Callable[[int], None],
                on_delete: Callable[[int], None]) -> None:
    row.toggled.connect(on_toggle)
    row.edit_requested.connect(on_edit)
    row.delete_requested.connect(on_delete)
