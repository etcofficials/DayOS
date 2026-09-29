from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QStackedLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.models import Goal
from src.services.dates import countdown_text, format_date, today
from src.ui.bus import bus
from src.ui.dialogs import DailyReviewDialog, TaskDialog
from src.ui.pages.base import Page
from src.ui.task_actions import TaskActions
from src.ui.widgets.common import (
    fit_list_items,
    EmptyState,
    FormDialog,
    OptionalDate,
    PageHeader,
    SegmentBar,
    ThinProgress,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    separator,
)
from src.ui.widgets.task_row import TaskRow, connect_row

STATUS_TONES = {"active": "accent", "paused": "amber", "completed": "blue"}


def _fmt(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".")


class GoalDialog(FormDialog):
    def __init__(self, ctx, parent=None, goal: Goal | None = None) -> None:
        super().__init__("Edit goal" if goal else "New goal", parent, width=500)
        self.ctx = ctx
        self.goal = goal
        self.title_edit = QLineEdit(goal.title if goal else "")
        self.title_edit.setPlaceholderText("e.g. Finish the physics syllabus")
        self.add_row("Goal", self.title_edit)
        self.desc = QPlainTextEdit(goal.description if goal else "")
        self.desc.setPlaceholderText("Why this matters, or what 'done' looks like")
        self.desc.setFixedHeight(70)
        self.add_row("Description", self.desc)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems([""] + ctx.goals.categories())
        self.category.setCurrentText(goal.category if goal else "")
        self.category.lineEdit().setPlaceholderText("e.g. School, Health, Personal")
        self.add_row("Category", self.category)
        self.target_date = OptionalDate("Target date", date.fromisoformat(goal.target_date) if goal and goal.target_date else None)
        self.add_row("Deadline", self.target_date)
        self.measurable = QCheckBox("Track a number (e.g. chapters, pages, km)")
        self.measurable.setChecked(bool(goal and goal.target_value))
        self.add_row("", self.measurable)
        row = QHBoxLayout()
        self.target = QDoubleSpinBox()
        self.target.setRange(0.01, 1_000_000_000)
        self.target.setDecimals(2)
        self.target.setValue(goal.target_value if goal and goal.target_value else 10)
        self.unit = QLineEdit(goal.unit if goal else "")
        self.unit.setPlaceholderText("unit, e.g. chapters")
        row.addWidget(self.target, 1)
        row.addWidget(self.unit, 1)
        self.add_row("Target", row)
        self.start_value = QDoubleSpinBox()
        self.start_value.setRange(0, 1_000_000_000)
        self.start_value.setDecimals(2)
        if not goal:
            self.add_row("Starting at", self.start_value)
        self.measurable.toggled.connect(self._toggle)
        self._toggle(self.measurable.isChecked())
        self.title_edit.setFocus()

    def _toggle(self, on: bool) -> None:
        for w in (self.target, self.unit, self.start_value):
            w.setEnabled(on)

    def save(self) -> None:
        fields = dict(
            description=self.desc.toPlainText(),
            category=self.category.currentText(),
            target_date=self.target_date.value(),
            target_value=self.target.value() if self.measurable.isChecked() else None,
            unit=self.unit.text() if self.measurable.isChecked() else "",
        )
        with self.ctx.db.transaction():
            if self.goal:
                self.ctx.goals.update(self.goal.id, title=self.title_edit.text(), **fields)
            else:
                goal_id = self.ctx.goals.create(self.title_edit.text(), **fields)
                if self.measurable.isChecked() and self.start_value.value() > 0:
                    self.ctx.goals.log_progress(goal_id, self.start_value.value(), "Starting point")
        bus.notify("goals")


class ProgressDialog(FormDialog):
    def __init__(self, ctx, goal: Goal, parent=None) -> None:
        super().__init__(f"Update progress", parent, save_text="Save progress")
        self.ctx = ctx
        self.goal = goal
        self.form.addRow(label(goal.title, "muted", wrap=True))
        self.value = QDoubleSpinBox()
        self.value.setRange(0, 1_000_000_000)
        self.value.setDecimals(2)
        self.value.setValue(goal.current_value)
        self.value.setSuffix(f" {goal.unit}" if goal.unit else "")
        row = QHBoxLayout()
        row.addWidget(self.value, 1)
        for step in (1, 5):
            row.addWidget(button(f"+{step}", "", on_click=lambda s=step: self.value.setValue(self.value.value() + s)))
        self.add_row("New total", row)
        if goal.target_value:
            self.form.addRow(label(f"Target: {_fmt(goal.target_value)} {goal.unit}".strip(), "caption"))
        self.note = QLineEdit()
        self.note.setPlaceholderText("What moved it forward? (optional)")
        self.add_row("Note", self.note)
        self.value.setFocus()
        self.value.selectAll()

    def save(self) -> None:
        self.ctx.goals.log_progress(self.goal.id, self.value.value(), self.note.text())
        bus.notify("goals")


class GoalsPage(Page):
    domains = ("goals", "tasks", "journal", "settings")
    title = "Goals"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.actions = TaskActions(ctx, self, lambda t, a, c: self.toast(t, a, c))
        self.selected_id: int | None = None
        header = PageHeader("Goals & reflection", "What you're working towards, and how your days are going.")
        header.add_action(button("New goal", "primary", "plus", self.new_item, "New goal (Ctrl+N)"))
        self.root.addWidget(header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.root.addWidget(self.tabs, 1)

        # -- goals tab
        goals_tab = QWidget()
        gl = QVBoxLayout(goals_tab)
        gl.setContentsMargins(0, 12, 0, 0)
        gl.setSpacing(12)
        self.filter = SegmentBar([("active", "Active"), ("paused", "Paused"), ("completed", "Completed"), ("all", "All")])
        self.filter.changed.connect(lambda _: self.refresh())
        gl.addWidget(self.filter)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(14)
        split.setChildrenCollapsible(False)
        left = QFrame()
        left.setProperty("panel", True)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 10, 10)
        self.list = QListWidget()
        self.list.setAccessibleName("Goals")
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list)
        left.setMinimumWidth(260)
        split.addWidget(left)
        right = QFrame()
        right.setProperty("panel", True)
        self.detail_stack = QStackedLayout(right)
        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(22, 18, 22, 18)
        self.detail_layout.setSpacing(10)
        self.detail_stack.addWidget(scroll_wrap(self.detail))
        self.empty = QWidget()
        self.empty_layout = QVBoxLayout(self.empty)
        self.detail_stack.addWidget(self.empty)
        split.addWidget(right)
        split.setSizes([320, 680])
        split.setStretchFactor(1, 1)
        gl.addWidget(split, 1)
        self.tabs.addTab(goals_tab, "Goals")

        # -- journal tab
        journal_tab = QWidget()
        jl = QVBoxLayout(journal_tab)
        jl.setContentsMargins(0, 12, 0, 0)
        row = QHBoxLayout()
        row.addWidget(label("Your daily intentions and end-of-day reviews.", "muted"), 1)
        row.addWidget(button("Write today's review", "", "moon", self._review))
        jl.addLayout(row)
        self.journal_holder = QWidget()
        self.journal_layout = QVBoxLayout(self.journal_holder)
        self.journal_layout.setContentsMargins(0, 0, 0, 0)
        self.journal_layout.setSpacing(12)
        jl.addWidget(scroll_wrap(self.journal_holder), 1)
        self.tabs.addTab(journal_tab, "Journal")

    # -- goals list -------------------------------------------------------------
    def refresh(self) -> None:
        status = self.filter.current()
        goals = self.ctx.goals.list(None if status == "all" else status)
        self.list.blockSignals(True)
        self.list.clear()
        select_item = None
        for goal in goals:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, goal.id)
            w = self._goal_item(goal)
            item.setSizeHint(w.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, w)
            if goal.id == self.selected_id:
                select_item = item
        self.list.blockSignals(False)
        fit_list_items(self.list)
        if select_item is None and self.list.count():
            select_item = self.list.item(0)
        if select_item:
            self.list.setCurrentItem(select_item)
            self._show_goal(int(select_item.data(Qt.ItemDataRole.UserRole)))
        else:
            self.selected_id = None
            clear_layout(self.empty_layout)
            names = {"active": "No active goals", "paused": "No paused goals", "completed": "No completed goals yet",
                     "all": "No goals yet"}
            self.empty_layout.addWidget(EmptyState(
                "goals", names[status],
                "A goal can be measurable (like '20 chapters') or simply something to work towards. "
                "You can link tasks to it and log progress over time.",
                [("New goal", self.new_item)] if status in ("active", "all") else []))
            self.detail_stack.setCurrentIndex(1)
        self._fill_journal()

    def _goal_item(self, goal: Goal) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 9, 8, 9)
        lay.setSpacing(6)
        top = QHBoxLayout()
        title = label(goal.title)
        title.setStyleSheet("font-weight: 600;")
        top.addWidget(title, 1)
        if goal.status != "active":
            top.addWidget(chip(goal.status.title(), STATUS_TONES[goal.status]))
        lay.addLayout(top)
        if goal.fraction is not None:
            lay.addWidget(ThinProgress(goal.fraction, "blue", 5))
        meta = []
        if goal.fraction is not None:
            meta.append(f"{round(goal.fraction * 100)}%")
        if goal.target_date and goal.status == "active":
            meta.append(countdown_text(date.fromisoformat(goal.target_date)))
        if goal.category:
            meta.append(goal.category)
        if meta:
            lay.addWidget(label(" · ".join(meta), "caption"))
        return w

    def _on_select(self, current, _prev) -> None:
        if current is not None:
            self._show_goal(int(current.data(Qt.ItemDataRole.UserRole)))

    # -- goal detail ------------------------------------------------------------
    def _show_goal(self, goal_id: int) -> None:
        goal = self.ctx.goals.get(goal_id)
        if goal is None:
            return
        self.selected_id = goal_id
        lay = self.detail_layout
        clear_layout(lay)
        top = QHBoxLayout()
        title = label(goal.title, "title", wrap=True)
        top.addWidget(title, 1)
        top.addWidget(chip(goal.status.title(), STATUS_TONES[goal.status]), 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        meta = []
        if goal.category:
            meta.append(goal.category)
        if goal.target_date:
            td = date.fromisoformat(goal.target_date)
            meta.append(f"Target {format_date(td, self.date_style)} ({countdown_text(td)})")
        meta.append(f"Started {goal.created_at[:10]}")
        if goal.completed_at:
            meta.append(f"Completed {goal.completed_at[:10]}")
        lay.addWidget(label(" · ".join(meta), "caption", wrap=True))
        if goal.description:
            lay.addWidget(label(goal.description, "muted", wrap=True, selectable=True))

        actions = QHBoxLayout()
        if goal.status == "active":
            actions.addWidget(button("Update progress", "primary", "chart", lambda: ProgressDialog(self.ctx, goal, self).exec()))
            actions.addWidget(button("Pause", "ghost", on_click=lambda: self._set_status(goal, "paused")))
            actions.addWidget(button("Mark completed", "ghost", "check", lambda: self._set_status(goal, "completed")))
        elif goal.status == "paused":
            actions.addWidget(button("Resume", "primary", on_click=lambda: self._set_status(goal, "active")))
            actions.addWidget(button("Mark completed", "ghost", "check", lambda: self._set_status(goal, "completed")))
        else:
            actions.addWidget(button("Reopen", "", on_click=lambda: self._set_status(goal, "active")))
        actions.addStretch(1)
        actions.addWidget(button("Edit", "ghost", "edit", lambda: GoalDialog(self.ctx, self, goal).exec()))
        actions.addWidget(button("Delete", "ghost", "trash", lambda: self._delete(goal)))
        lay.addLayout(actions)

        if goal.fraction is not None:
            lay.addWidget(separator())
            row = QHBoxLayout()
            row.addWidget(label(f"{_fmt(goal.current_value)} of {_fmt(goal.target_value or 0)} {goal.unit}".strip(), "metric"))
            row.addStretch(1)
            row.addWidget(label(f"{round(goal.fraction * 100)}%", "section"))
            lay.addLayout(row)
            lay.addWidget(ThinProgress(goal.fraction, "blue", 8))
            if goal.fraction >= 1 and goal.status == "active":
                lay.addWidget(label("You've reached the target. Mark the goal completed when it feels done.", "success", wrap=True))

        lay.addWidget(separator())
        tasks = self.ctx.tasks.for_goal(goal.id)
        head = QHBoxLayout()
        head.addWidget(label(f"Linked tasks ({sum(1 for t in tasks if t.done)}/{len(tasks)} done)" if tasks else "Linked tasks", "section"), 1)
        head.addWidget(button("Add task", "link", "plus", lambda: TaskDialog(self.ctx, self, default_goal=goal.id).exec()))
        lay.addLayout(head)
        if tasks:
            ref = today()
            for task in tasks[:30]:
                row_w = TaskRow(task, ref, clock24=self.clock24, date_style=self.date_style, compact=True)
                connect_row(row_w, self.actions.toggle, self.actions.edit, self.actions.delete)
                lay.addWidget(row_w)
            lay.addWidget(label("Completing linked tasks doesn't complete the goal — you decide when it's done.", "caption", wrap=True))
        else:
            lay.addWidget(label("Break the goal into tasks and link them here to see steady progress.", "muted", wrap=True))

        history = self.ctx.goals.history(goal.id)
        lay.addWidget(separator())
        lay.addWidget(label("Progress history", "section"))
        if history:
            for entry in history[:50]:
                r = QHBoxLayout()
                r.addWidget(label(format_date(date.fromisoformat(entry.date), self.date_style), "muted"))
                r.addWidget(label(f"{_fmt(entry.value)} {goal.unit}".strip()))
                r.addWidget(label(entry.note, "caption", wrap=True), 1)
                lay.addLayout(r)
        else:
            lay.addWidget(label("No progress logged yet." if goal.target_value else
                                "This goal isn't measured with a number — link tasks or add notes to the description.",
                                "muted", wrap=True))
        lay.addStretch(1)
        self.detail_stack.setCurrentIndex(0)

    def _set_status(self, goal: Goal, status: str) -> None:
        if guarded(self, lambda: self.ctx.goals.set_status(goal.id, status)):
            bus.notify("goals")
            self.toast({"completed": "Goal completed — well done", "paused": "Goal paused",
                        "active": "Goal active"}[status])

    def _delete(self, goal: Goal) -> None:
        if confirm(self, "Delete goal?",
                   f"“{goal.title}” and its progress history will be deleted. "
                   f"Linked tasks are kept but will no longer be linked."):
            if guarded(self, lambda: self.ctx.goals.delete(goal.id)):
                self.selected_id = None
                bus.notify("goals", "tasks")
                self.toast("Goal deleted")

    # -- journal ---------------------------------------------------------------
    def _fill_journal(self) -> None:
        clear_layout(self.journal_layout)
        entries = self.ctx.journal.recent(60)
        if not entries:
            self.journal_layout.addWidget(EmptyState(
                "moon", "No reflections yet",
                "Set an intention on the Today page in the morning, and write a short review in the evening.",
                [("Write today's review", self._review)]))
            return
        for entry in entries:
            card = QFrame()
            card.setProperty("card", True)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(18, 14, 18, 14)
            cl.setSpacing(4)
            d = date.fromisoformat(entry.date)
            head = QHBoxLayout()
            head.addWidget(label(format_date(d, self.date_style, with_weekday=True), "section"), 1)
            head.addWidget(button("Edit", "link", on_click=lambda d=d: DailyReviewDialog(self.ctx, self, d).exec()))
            cl.addLayout(head)
            for caption, text in (("Intention", entry.intention), ("Went well", entry.went_well),
                                  ("Reflection", entry.reflection)):
                if text:
                    cl.addWidget(label(caption, "caption"))
                    cl.addWidget(label(text, "", wrap=True, selectable=True))
            self.journal_layout.addWidget(card)
        self.journal_layout.addStretch(1)

    def _review(self) -> None:
        DailyReviewDialog(self.ctx, self).exec()

    def new_item(self) -> None:
        self.tabs.setCurrentIndex(0)
        dlg = GoalDialog(self.ctx, self)
        if dlg.exec():
            self.filter.set_current("active")
            self.selected_id = None
            self.refresh()
