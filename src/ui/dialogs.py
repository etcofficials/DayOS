"""Dialogs shared by several pages (tasks, quick capture, study log, daily review)."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.context import AppContext
from src.models import Task
from src.services.dates import ValidationError, format_duration, today
from src.ui.bus import bus
from src.ui.widgets.common import (
    DateEdit,
    FormDialog,
    IdCombo,
    OptionalDate,
    OptionalTime,
    TimeEdit,
    button,
    label,
    tool_button,
)


def subject_items(ctx: AppContext) -> list[tuple[int, str]]:
    return [(s.id, s.name) for s in ctx.subjects.list()]


class ChecklistEditor(QWidget):
    def __init__(self, items: list[tuple[str, bool]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)
        self.rows: list[tuple[QWidget, QCheckBox, QLineEdit]] = []
        self.add_btn = button("Add checklist item", "link", "plus", on_click=lambda: self.add_row("", False, focus=True))
        self.lay.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        for title, done in items or []:
            self.add_row(title, done)

    def add_row(self, title: str, done: bool, focus: bool = False) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        check = QCheckBox()
        check.setChecked(done)
        check.setAccessibleName("Checklist item done")
        edit = QLineEdit(title)
        edit.setPlaceholderText("Checklist item")
        remove = tool_button("close", "Remove item", size=14)
        h.addWidget(check)
        h.addWidget(edit, 1)
        h.addWidget(remove)
        entry = (row, check, edit)
        self.rows.append(entry)
        remove.clicked.connect(lambda: self._remove(entry))
        edit.returnPressed.connect(lambda: self.add_row("", False, focus=True))
        self.lay.insertWidget(self.lay.count() - 1, row)
        if focus:
            edit.setFocus()

    def _remove(self, entry: tuple[QWidget, QCheckBox, QLineEdit]) -> None:
        if entry in self.rows:
            self.rows.remove(entry)
            entry[0].deleteLater()

    def items(self) -> list[tuple[str, bool]]:
        return [(edit.text().strip(), check.isChecked()) for _, check, edit in self.rows if edit.text().strip()]


class TaskDialog(FormDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None, task: Task | None = None,
                 default_due: date | None = None, default_goal: int | None = None) -> None:
        super().__init__("Edit task" if task else "New task", parent, width=520)
        self.ctx = ctx
        self.task = task
        clock24 = bool(ctx.settings.get("clock_24h"))
        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("What needs doing?")
        self.add_row("Title", self.title_edit)
        self.desc = QPlainTextEdit(task.description if task else "")
        self.desc.setPlaceholderText("Optional details")
        self.desc.setFixedHeight(70)
        self.add_row("Notes", self.desc)
        self.due = OptionalDate("Due", task.due if task else default_due)
        self.due.edit.set_first_weekday(int(ctx.settings.get("week_start")))
        self.add_row("Due date", self.due)
        self.time = OptionalTime("At", task.due_time if task else None, clock24)
        self.time.setEnabled(self.due.value() is not None)
        self.due.toggled.connect(self._due_toggled)
        self.add_row("Due time", self.time)
        self.priority = QComboBox()
        self.priority.addItems(["Low", "Normal", "High"])
        self.priority.setCurrentIndex(task.priority if task else 1)
        self.add_row("Priority", self.priority)
        self.subject = IdCombo("No subject")
        self.subject.set_items(subject_items(ctx))
        self.subject.set_current_id(task.subject_id if task else None)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems([""] + ctx.tasks.categories())
        self.category.setCurrentText(task.category if task else "")
        self.category.lineEdit().setPlaceholderText("e.g. Homework, Personal")
        row = QHBoxLayout()
        row.addWidget(self.subject, 1)
        row.addWidget(self.category, 1)
        self.add_row("Subject / category", row)
        self.goal = IdCombo("Not linked to a goal")
        goals = [(g.id, g.title) for g in ctx.goals.list() if g.status != "completed" or (task and task.goal_id == g.id)]
        self.goal.set_items(goals)
        self.goal.set_current_id(task.goal_id if task else default_goal)
        self.add_row("Goal", self.goal)
        self.estimate = QSpinBox()
        self.estimate.setRange(0, 1440)
        self.estimate.setSingleStep(5)
        self.estimate.setSuffix(" min")
        self.estimate.setSpecialValueText("No estimate")
        self.estimate.setValue(task.estimate_minutes or 0 if task else 0)
        self.add_row("Estimate", self.estimate)
        subs = [(s.title, bool(s.done)) for s in ctx.tasks.subtasks(task.id)] if task else []
        self.checklist = ChecklistEditor(subs)
        self.add_row("Checklist", self.checklist)
        self.title_edit.setFocus()

    def _due_toggled(self, on: bool) -> None:
        self.time.setEnabled(on)
        if not on:
            self.time.set_value(None)

    def save(self) -> None:
        fields = dict(
            title=self.title_edit.text(),
            description=self.desc.toPlainText(),
            due_date=self.due.value(),
            due_time=self.time.value() if self.due.value() else None,
            priority=self.priority.currentIndex(),
            subject_id=self.subject.current_id(),
            category=self.category.currentText(),
            goal_id=self.goal.current_id(),
            estimate_minutes=self.estimate.value() or None,
        )
        with self.ctx.db.transaction():
            if self.task:
                self.ctx.tasks.update(self.task.id, **fields)
                task_id = self.task.id
            else:
                task_id = self.ctx.tasks.create(**fields)
            self.ctx.tasks.replace_subtasks(task_id, self.checklist.items())
        bus.notify("tasks", "goals")


class QuickNoteDialog(FormDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("Quick note", parent, save_text="Save note", width=500)
        self.ctx = ctx
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Title (optional)")
        self.add_row("Title", self.title_edit)
        self.content = QPlainTextEdit()
        self.content.setPlaceholderText("Capture a thought, idea or reminder…")
        self.content.setMinimumHeight(150)
        self.add_row("Note", self.content)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("Tags, separated by commas")
        self.add_row("Tags", self.tags)
        self.content.setFocus()

    def save(self) -> None:
        text = self.content.toPlainText()
        if not text.strip() and not self.title_edit.text().strip():
            raise ValidationError("Write something first — the note is empty.")
        self.ctx.notes.create(self.title_edit.text(), text, self.tags.text())
        bus.notify("notes")


class ManualStudyDialog(FormDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None, subject_id: int | None = None) -> None:
        super().__init__("Log a study session", parent, save_text="Save session")
        self.ctx = ctx
        self.subject = IdCombo("No subject")
        self.subject.set_items(subject_items(ctx))
        self.subject.set_current_id(subject_id)
        self.add_row("Subject", self.subject)
        self.day = DateEdit(today())
        self.day.setMaximumDate(self.day.date())
        self.add_row("Date", self.day)
        now = datetime.now()
        self.start = TimeEdit(now.time().replace(second=0, microsecond=0), bool(ctx.settings.get("clock_24h")))
        self.add_row("Started at", self.start)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 16 * 60)
        self.minutes.setValue(30)
        self.minutes.setSuffix(" min")
        self.add_row("Duration", self.minutes)
        self.note = QLineEdit()
        self.note.setPlaceholderText("What did you work on? (optional)")
        self.add_row("Note", self.note)

    def save(self) -> None:
        self.ctx.study.record_manual(
            self.subject.current_id(), self.day.value(), self.start.value(), self.minutes.value(), self.note.text()
        )
        bus.notify("study")


class DailyReviewDialog(FormDialog):
    """End-of-day reflection with a factual summary of the day."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None, day: date | None = None) -> None:
        self.day = day or today()
        super().__init__("End-of-day review", parent, save_text="Save review", width=540)
        self.ctx = ctx
        entry = ctx.journal.get(self.day)
        overdue, due = ctx.tasks.for_day(self.day)
        done_today = ctx.tasks.completed_on(self.day)
        study = ctx.study.seconds_on(self.day)
        habits = ctx.habits.scheduled_on(self.day)
        done_habits = ctx.habits.done_on(self.day)
        habit_done = sum(1 for h in habits if h.id in done_habits)
        facts = [
            f"Tasks completed today: {done_today}",
            f"Still open from today's list: {sum(1 for t in due if not t.done)}"
            + (f" (+{len(overdue)} overdue)" if overdue else ""),
            f"Study time: {format_duration(study) if study else 'none recorded'}",
        ]
        if habits:
            facts.append(f"Habits: {habit_done} of {len(habits)} done")
        if entry.intention:
            facts.insert(0, f"This morning's intention: “{entry.intention}”")
        summary = label("\n".join(facts), "muted", wrap=True)
        self.form.addRow(summary)
        self.went_well = QPlainTextEdit(entry.went_well)
        self.went_well.setPlaceholderText("Something that went well, however small")
        self.went_well.setFixedHeight(70)
        self.add_row("Went well", self.went_well)
        self.reflection = QPlainTextEdit(entry.reflection)
        self.reflection.setPlaceholderText("What would you like to remember or carry into tomorrow?")
        self.reflection.setFixedHeight(110)
        self.add_row("Reflection", self.reflection)

    def save(self) -> None:
        self.ctx.journal.save(self.day, went_well=self.went_well.toPlainText(), reflection=self.reflection.toPlainText())
        bus.notify("journal")
