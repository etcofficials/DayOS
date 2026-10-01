"""Dialogs shared by several pages (tasks, quick capture, study log, daily review)."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateTimeEdit,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.context import AppContext
from src.models import Task
from src.services import recurrence
from src.services.dates import ValidationError, format_duration, today
from src.ui.bus import bus
from src.ui.widgets.common import (
    CollapsibleSection,
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
from src.ui.widgets.links import LinksPanel


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
    """Create or edit a task. Everyday fields first; the rest lives under "More options"."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None, task: Task | None = None,
                 default_due: date | None = None, default_goal: int | None = None,
                 default_project: int | None = None, default_title: str = "") -> None:
        super().__init__("Edit task" if task else "New task", parent, width=560)
        self.ctx = ctx
        self.task = task
        clock24 = bool(ctx.settings.get("clock_24h"))
        self.title_edit = QLineEdit(task.title if task else default_title)
        self.title_edit.setPlaceholderText("What needs doing?")
        self.add_row("Title", self.title_edit)
        self.desc = QPlainTextEdit(task.description if task else "")
        self.desc.setPlaceholderText("Optional details")
        self.desc.setFixedHeight(64)
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
        subs = [(s.title, bool(s.done)) for s in ctx.tasks.subtasks(task.id)] if task else []
        self.checklist = ChecklistEditor(subs)
        self.add_row("Checklist", self.checklist)

        self.more = CollapsibleSection("More options: project, tags, repeat, reminder, links",
                                       expanded=bool(task and (task.project_id or task.tags or task.recurrence)))
        self.extra.addWidget(self.more)
        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.more.body.addLayout(form)
        self.project = IdCombo("No project")
        self.project.set_items(ctx.projects.choices())
        if task and task.project_id and self.project.findData(task.project_id) < 0 and task.project_name:
            self.project.addItem(task.project_name, task.project_id)
        self.project.set_current_id(task.project_id if task else default_project)
        form.addRow("Project", self.project)
        self.tags = QLineEdit(task.tags if task else "")
        self.tags.setPlaceholderText("Comma-separated, e.g. reading, errands")
        completer = QCompleter(ctx.tasks.tags(), self.tags)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tags.setCompleter(completer)
        form.addRow("Tags", self.tags)
        self.goal = IdCombo("Not linked to a goal")
        goals = [(g.id, g.title) for g in ctx.goals.list() if g.status != "completed" or (task and task.goal_id == g.id)]
        self.goal.set_items(goals)
        self.goal.set_current_id(task.goal_id if task else default_goal)
        form.addRow("Goal", self.goal)
        rep = QHBoxLayout()
        self.repeat = QComboBox()
        for key, text in recurrence.RULES.items():
            self.repeat.addItem(text, key)
        self.repeat.setCurrentIndex(max(0, self.repeat.findData(task.recurrence if task else "")))
        self.interval = QSpinBox()
        self.interval.setRange(1, 365)
        self.interval.setPrefix("every ")
        self.interval.setValue(task.recur_interval if task else 1)
        self.interval.setAccessibleName("Repeat interval")
        rep.addWidget(self.repeat, 1)
        rep.addWidget(self.interval)
        self.repeat.currentIndexChanged.connect(self._repeat_changed)
        self._repeat_changed()
        form.addRow("Repeat", rep)
        reminder = ctx.reminders.for_task(task.id) if task else None
        rem_row = QHBoxLayout()
        self.remind = QCheckBox("Remind me")
        self.remind_at = QDateTimeEdit()
        self.remind_at.setCalendarPopup(True)
        self.remind_at.setDisplayFormat("ddd d MMM yyyy  " + ("HH:mm" if clock24 else "h:mm AP"))
        if reminder:
            self.remind.setChecked(True)
            self.remind_at.setDateTime(datetime.fromisoformat(reminder.due_at))
        else:
            base = datetime.combine(task.due, datetime.strptime(task.due_time, "%H:%M").time()) \
                if task and task.due and task.due_time else datetime.now().replace(second=0, microsecond=0)
            self.remind_at.setDateTime(base)
        self.remind_at.setEnabled(self.remind.isChecked())
        self.remind.toggled.connect(self.remind_at.setEnabled)
        rem_row.addWidget(self.remind)
        rem_row.addWidget(self.remind_at, 1)
        form.addRow("Reminder", rem_row)
        est = QHBoxLayout()
        self.estimate = QSpinBox()
        self.estimate.setRange(0, 1440)
        self.estimate.setSingleStep(5)
        self.estimate.setSuffix(" min")
        self.estimate.setSpecialValueText("No estimate")
        self.estimate.setValue(task.estimate_minutes or 0 if task else 0)
        self.actual = QSpinBox()
        self.actual.setRange(0, 100000)
        self.actual.setSingleStep(5)
        self.actual.setSuffix(" min spent")
        self.actual.setSpecialValueText("Not tracked")
        self.actual.setValue(task.actual_minutes or 0 if task else 0)
        self.actual.setToolTip("Focus sessions linked to this task add their time here automatically.")
        est.addWidget(self.estimate, 1)
        est.addWidget(self.actual, 1)
        form.addRow("Estimate / actual", est)
        self.waiting = LinksPanelDeps(ctx, task)
        form.addRow("Waiting on", self.waiting)
        self.links = LinksPanel(ctx, "task", task.id if task else None, ["note", "project", "goal", "event"])
        form.addRow("Linked", self.links)
        self.title_edit.setFocus()

    def _due_toggled(self, on: bool) -> None:
        self.time.setEnabled(on)
        if not on:
            self.time.set_value(None)

    def _repeat_changed(self) -> None:
        rule = self.repeat.currentData()
        self.interval.setEnabled(rule not in ("", "weekdays"))

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
            actual_minutes=self.actual.value() or None,
            project_id=self.project.current_id(),
            tags=self.tags.text(),
            recurrence=self.repeat.currentData(),
            recur_interval=self.interval.value(),
        )
        remind_at = self.remind_at.dateTime().toPython() if self.remind.isChecked() else None
        with self.ctx.db.transaction():
            if self.task:
                self.ctx.tasks.update(self.task.id, **fields)
                task_id = self.task.id
            else:
                task_id = self.ctx.tasks.create(**fields)
            self.ctx.tasks.replace_subtasks(task_id, self.checklist.items())
            self.ctx.tasks.set_dependencies(task_id, self.waiting.ids())
            current = self.ctx.reminders.for_task(task_id)
            if remind_at is None or current is None or current.due_at[:16] != remind_at.strftime("%Y-%m-%d %H:%M"):
                self.ctx.reminders.set_task_reminder(task_id, fields["title"].strip(), remind_at)
            self.links.apply(task_id)
        self.saved_id = task_id
        bus.notify("tasks", "goals", "reminders")


class LinksPanelDeps(QWidget):
    """Tasks this task is waiting on (dependencies)."""

    def __init__(self, ctx: AppContext, task: Task | None) -> None:
        super().__init__()
        self.ctx = ctx
        self.task = task
        self._ids: list[tuple[int, str]] = [(t.id, t.title) for t in ctx.tasks.dependencies(task.id)] if task else []
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(2)
        self.rows = QVBoxLayout()
        self.lay.addLayout(self.rows)
        add = button("Add a task to wait on…", "link", "plus", self._add)
        self.lay.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        self._fill()

    def _fill(self) -> None:
        from src.ui.widgets.common import clear_layout

        clear_layout(self.rows)
        for tid, title in self._ids:
            r = QHBoxLayout()
            r.addWidget(label(title, "", wrap=True), 1)
            r.addWidget(tool_button("close", "Stop waiting on this task", lambda t=tid: self._remove(t), 14))
            self.rows.addLayout(r)

    def _add(self) -> None:
        from src.ui.widgets.links import ItemPicker

        exclude = {("task", tid) for tid, _ in self._ids}
        if self.task:
            exclude.add(("task", self.task.id))
        picker = ItemPicker(self.ctx, ["task"], self, "Wait on which task?", exclude)
        if picker.exec() and picker.choice is not None:
            self._ids.append((picker.choice.ref_id, picker.choice.title))
            self._fill()

    def _remove(self, task_id: int) -> None:
        self._ids = [x for x in self._ids if x[0] != task_id]
        self._fill()

    def ids(self) -> list[int]:
        return [tid for tid, _ in self._ids]


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
    """End-of-day reflection with a factual, non-judgemental summary of the day."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None, day: date | None = None) -> None:
        from src.services.reviews import day_summary

        self.day = day or today()
        super().__init__("End-of-day review", parent, save_text="Save review", width=580)
        self.ctx = ctx
        entry = ctx.journal.get(self.day)
        summary = day_summary(ctx, self.day)
        facts = []
        if entry.intention:
            facts.append(f"This morning's intention: “{entry.intention}”")
        facts.append(f"Completed: {len(summary.completed)} task{'s' if len(summary.completed) != 1 else ''}"
                     + (" — " + ", ".join(summary.completed[:4]) + ("…" if len(summary.completed) > 4 else "")
                        if summary.completed else ""))
        if summary.still_open:
            facts.append(f"Still open (they can carry over): {', '.join(summary.still_open[:4])}"
                         + ("…" if len(summary.still_open) > 4 else ""))
        if summary.overdue:
            facts.append(f"Older open tasks: {summary.overdue}")
        facts.append(f"Focus time: {format_duration(summary.study_minutes * 60) if summary.study_minutes else 'none recorded'}"
                     + (f" in {summary.study_sessions} session{'s' if summary.study_sessions != 1 else ''}"
                        if summary.study_sessions else ""))
        if summary.habits_scheduled:
            facts.append(f"Habits: {summary.habits_done} of {summary.habits_scheduled}")
        if summary.events:
            facts.append("On the calendar: " + "; ".join(summary.events[:4]))
        box = label("\n".join(facts), "muted", wrap=True)
        self.form.addRow(box)
        self.went_well = QPlainTextEdit(entry.went_well)
        self.went_well.setPlaceholderText("Something that went well, however small")
        self.went_well.setFixedHeight(64)
        self.add_row("Went well", self.went_well)
        self.improve = QPlainTextEdit(entry.improve)
        self.improve.setPlaceholderText("One thing to try differently tomorrow")
        self.improve.setFixedHeight(64)
        self.add_row("Tomorrow", self.improve)
        self.reflection = QPlainTextEdit(entry.reflection)
        self.reflection.setPlaceholderText("Anything else you'd like to remember?")
        self.reflection.setFixedHeight(90)
        self.add_row("Reflection", self.reflection)

    def save(self) -> None:
        self.ctx.journal.save(self.day, went_well=self.went_well.toPlainText(), reflection=self.reflection.toPlainText(),
                              improve=self.improve.toPlainText())
        bus.notify("journal")
